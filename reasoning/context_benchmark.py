import copy
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import reasoner
from reasoning.context import choose_with_context
from reasoning.evaluate import evaluate_context_selection, evaluate_refinement
from reasoning.render_check import check_renderable


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = _PROJECT_ROOT / "artifacts" / "context_conflict_samples.json"
DEFAULT_OUTPUT = _PROJECT_ROOT / "artifacts" / "context_benchmark_results.json"


def _refine_with_context(sample: dict, context_result: dict) -> dict:
    # Replay one response to avoid a second paid request for refine.
    with patch.object(reasoner, "choose_with_context", return_value=context_result):
        return reasoner.refine(sample["image_path"], sample["candidates"])


def _refine_and_render(sample: dict, context_result: dict) -> dict:
    refine_result = _refine_with_context(sample, context_result)
    render_result = check_renderable(refine_result["final_latex"])
    return {
        "refine_result": refine_result,
        "render_result": render_result,
        "renderable": render_result["renderable"],
    }


def _validate_samples(samples: list[dict]) -> None:
    if not isinstance(samples, list) or not samples:
        raise ValueError("benchmark samples must not be empty")
    sample_ids = [sample.get("sample_id") for sample in samples]
    if any(not isinstance(sample_id, str) or not sample_id.strip() for sample_id in sample_ids):
        raise ValueError("each benchmark sample must have a non-blank sample_id")
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("benchmark sample_id values must be unique")

    for sample in samples:
        image_path = sample["image_path"]
        if not isinstance(image_path, str) or not image_path.strip():
            raise ValueError("benchmark image_path must be a non-blank string")
        candidates = sample["candidates"]
        if len(candidates) < 2:
            raise ValueError("benchmark requires at least two candidates per sample")
        if len(reasoner.deduplicate_candidates(candidates)) != len(candidates):
            raise ValueError("benchmark candidates must be valid and unique")
        ground_truth = reasoner.normalize_latex(sample["ground_truth"])
        if not ground_truth:
            raise ValueError("benchmark ground_truth must not be empty")
        expected_index = sample["expected_index"]
        if type(expected_index) is not int or not 0 <= expected_index < len(candidates):
            raise ValueError("benchmark expected_index is out of range")
        if reasoner.normalize_latex(candidates[expected_index]["latex"]) != ground_truth:
            raise ValueError("expected candidate must match ground_truth")


def _evaluate_and_write(
    results: list[dict],
    sample_type: str,
    output_path: str | Path,
    metadata: dict | None = None,
) -> dict:
    summary = None
    if all("refine_result" in result for result in results):
        baseline_samples = []
        for result in results:
            baseline_refine_result = {
                **result["refine_result"],
                "raw_latex": result["candidates"][0]["latex"],
            }
            baseline_samples.append({**result, "refine_result": baseline_refine_result})

        summary = evaluate_refinement(baseline_samples)
        summary["context_latency_ms"] = summary.pop("refine_latency_ms")
        summary.update(evaluate_context_selection(results))
    report = {
        "model": os.environ.get("OPENAI_MODEL"),
        "sample_type": sample_type,
        "summary": summary,
        "results": results,
        **(metadata or {}),
    }
    output_path = Path(output_path)
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    try:
        temporary_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return report


def run_context_benchmark(
    input_path: str | Path = DEFAULT_INPUT,
    output_path: str | Path = DEFAULT_OUTPUT,
) -> dict:
    input_path = Path(input_path)
    output_path = Path(output_path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("benchmark output must not overwrite the input dataset")
    if not output_path.parent.is_dir():
        raise FileNotFoundError("benchmark output directory does not exist")
    dataset = json.loads(input_path.read_text(encoding="utf-8"))
    _validate_samples(dataset["samples"])

    results = []
    for sample in dataset["samples"]:
        started = time.perf_counter()
        context_result = choose_with_context(sample["image_path"], sample["candidates"])
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        results.append(
            {
                **sample,
                "context_result": context_result,
                "latency_ms": latency_ms,
            }
        )
        # Persist each paid response before refine, later inputs, or rendering can fail.
        _evaluate_and_write(
            results,
            dataset["sample_type"],
            output_path,
            {"evaluation_status": "context_response_saved_refine_pending"},
        )
        results[-1]["refine_result"] = _refine_with_context(sample, context_result)
        _evaluate_and_write(
            results,
            dataset["sample_type"],
            output_path,
            {"evaluation_status": "context_responses_saved_render_pending"},
        )

    for result in results:
        render_result = check_renderable(result["refine_result"]["final_latex"])
        result["render_result"] = render_result
        result["renderable"] = render_result["renderable"]

    return _evaluate_and_write(
        results,
        dataset["sample_type"],
        output_path,
        {"evaluation_status": "complete"},
    )


def replay_context_benchmark(
    input_path: str | Path,
    output_path: str | Path,
) -> dict:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("replay output must not overwrite the saved source report")
    saved_report = json.loads(Path(input_path).read_text(encoding="utf-8"))
    results = copy.deepcopy(saved_report["results"])
    for result in results:
        result.update(_refine_and_render(result, result["context_result"]))

    metadata = {
        "model": saved_report["model"],
        "source": str(input_path),
        "method": "offline_replay_of_saved_context_results_with_render_check",
        "additional_api_calls": 0,
        "evaluation_status": "complete",
        "latency_note": "context_latency_ms contains historical request latency, not replay timing.",
        "render_note": "KaTeX renderability is independent of exact transcription and structural review.",
    }
    for key in ("evaluation_scope", "review_note"):
        if key in saved_report:
            metadata[key] = saved_report[key]
    if "latency_note" in saved_report:
        metadata["source_latency_note"] = saved_report["latency_note"]

    return _evaluate_and_write(
        results,
        saved_report["sample_type"],
        output_path,
        metadata,
    )


if __name__ == "__main__":
    print(json.dumps(run_context_benchmark()["summary"], ensure_ascii=False, indent=2))
