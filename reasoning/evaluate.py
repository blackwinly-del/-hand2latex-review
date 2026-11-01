import math
import statistics

from reasoner import normalize_latex


def evaluate_refinement(samples: list[dict]) -> dict:
    if not isinstance(samples, list):
        raise TypeError("samples must be a list")
    if not samples:
        raise ValueError("samples must not be empty")

    renderable_presence = ["renderable" in sample for sample in samples]
    if any(renderable_presence) and not all(renderable_presence):
        raise ValueError("renderable must be provided for all samples or none")

    raw_correct_count = 0
    final_correct_count = 0
    erroneous_rewrite_count = 0
    review_count = 0
    latencies = []
    renderable_flags = []

    for sample in samples:
        ground_truth = normalize_latex(sample["ground_truth"])
        if not ground_truth:
            raise ValueError("ground_truth must not be empty")

        result = sample["refine_result"]
        raw_correct = normalize_latex(result["raw_latex"]) == ground_truth
        final_correct = normalize_latex(result["final_latex"]) == ground_truth
        if not isinstance(result["need_review"], bool):
            raise TypeError("need_review must be a bool")

        latency = sample["latency_ms"]
        if isinstance(latency, bool) or not isinstance(latency, (int, float)):
            raise TypeError("latency_ms must be numeric")
        if not math.isfinite(latency):
            raise ValueError("latency_ms must be finite")
        if latency < 0:
            raise ValueError("latency_ms must not be negative")

        raw_correct_count += raw_correct
        final_correct_count += final_correct
        erroneous_rewrite_count += raw_correct and not final_correct
        review_count += result["need_review"]
        latencies.append(latency)
        if "renderable" in sample:
            if not isinstance(sample["renderable"], bool):
                raise TypeError("renderable must be a bool")
            renderable_flags.append(sample["renderable"])

    sample_count = len(samples)
    sorted_latencies = sorted(latencies)
    p95_index = math.ceil(0.95 * sample_count) - 1

    return {
        "sample_count": sample_count,
        "raw_correct_count": raw_correct_count,
        "final_correct_count": final_correct_count,
        "erroneous_rewrite_count": erroneous_rewrite_count,
        "review_count": review_count,
        "raw_exact_accuracy": raw_correct_count / sample_count,
        "final_exact_accuracy": final_correct_count / sample_count,
        "erroneous_rewrite_rate": (
            erroneous_rewrite_count / raw_correct_count
            if raw_correct_count
            else None
        ),
        "renderable_rate": (
            sum(renderable_flags) / sample_count if renderable_flags else None
        ),
        "human_review_rate": review_count / sample_count,
        "refine_latency_ms": {
            "median": statistics.median(latencies),
            "p95": sorted_latencies[p95_index],
        },
    }
