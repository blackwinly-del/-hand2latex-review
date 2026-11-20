"""用用户确认过的手写样本真值，评估 B+C 的真实转录准确率。

评估口径与 C 的 ``evaluate_refinement`` 一致：只做 ``strip`` 后整串精确匹配，
不做语义等价或"看起来像"的宽松判定。真值文件里每条的 ground_truth 都来自
用户逐条确认，脚本不生成、不修改真值。

单独运行：
    python -m reasoning.handwritten_eval
    python -m reasoning.handwritten_eval --output artifacts/handwritten_eval_gpu.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Callable

from reasoner import normalize_latex, refine
from reasoning.evaluate import evaluate_refinement
from recognizer import recognize

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MANIFEST = _ROOT / "data" / "handwritten_ground_truth.json"


def load_manifest(path: str | Path = _DEFAULT_MANIFEST) -> dict:
    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("manifest samples must be a non-empty list")
    for sample in samples:
        if not isinstance(sample, dict):
            raise TypeError("each manifest sample must be a dict")
        for key in ("sample_id", "image_path", "ground_truth"):
            value = sample.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"manifest sample is missing {key}")
    return data


def _resolve_image(image_path: str, base_dir: Path) -> Path:
    path = Path(image_path)
    return path if path.is_absolute() else base_dir / path


def _empty_refine_result() -> dict:
    return {
        "raw_latex": "",
        "final_latex": "",
        "confidence": "low",
        "changes": [],
        "need_review": True,
        "risk_score": None,
    }


def evaluate_handwritten(
    samples: list[dict],
    *,
    recognize_fn: Callable[[str], list[dict]] = recognize,
    refine_fn: Callable[[str, list[dict]], dict] = refine,
    base_dir: Path = _ROOT,
) -> dict:
    started = time.perf_counter()
    records = []
    eval_samples = []

    for sample in samples:
        image_path = _resolve_image(sample["image_path"], base_dir)
        candidates: list[dict] = []
        error: str | None = None
        try:
            candidates = recognize_fn(str(image_path))
            if not isinstance(candidates, list):
                raise TypeError(f"recognize must return a list, got {type(candidates).__name__}")
            result = refine_fn(str(image_path), candidates)
        except Exception as exc:  # noqa: BLE001 - 单个样本失败不能中断整轮评估
            error = f"{type(exc).__name__}: {exc}"
            result = _empty_refine_result()

        latency_ms = 0.0
        if candidates and isinstance(candidates[0], dict):
            raw_latency = candidates[0].get("latency_ms")
            if isinstance(raw_latency, (int, float)) and not isinstance(raw_latency, bool):
                latency_ms = max(0.0, float(raw_latency))

        ground_truth = normalize_latex(sample["ground_truth"])
        raw_latex = normalize_latex(result.get("raw_latex", ""))
        final_latex = normalize_latex(result.get("final_latex", ""))
        try:
            display_path = image_path.relative_to(base_dir).as_posix()
        except ValueError:
            display_path = str(image_path)

        records.append(
            {
                "sample_id": sample["sample_id"],
                "image_path": display_path,
                "ground_truth": ground_truth,
                "candidates": candidates,
                "raw_latex": raw_latex,
                "final_latex": final_latex,
                "raw_correct": raw_latex == ground_truth,
                "final_correct": final_latex == ground_truth,
                "confidence": result.get("confidence"),
                "need_review": bool(result.get("need_review")),
                "error": error,
            }
        )
        eval_samples.append(
            {
                "ground_truth": ground_truth,
                "refine_result": result,
                "latency_ms": latency_ms,
            }
        )

    summary = evaluate_refinement(eval_samples)
    return {
        "sample_count": len(records),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "recognizer_backend": (os.environ.get("RECOGNIZER_BACKEND") or "paddle").strip(),
            "recognizer_device": (os.environ.get("RECOGNIZER_DEVICE") or "cpu").strip(),
            "recognizer_model": (os.environ.get("RECOGNIZER_MODEL") or "PP-FormulaNet-L").strip(),
        },
        "summary": summary,
        "results": records,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _print_report(report: dict) -> None:
    summary = report["summary"]
    env = report["environment"]
    print(
        f"设备={env['recognizer_device']} 后端={env['recognizer_backend']} "
        f"模型={env['recognizer_model']}"
    )
    print(
        f"样本={summary['sample_count']} "
        f"raw 精确={summary['raw_correct_count']}/{summary['sample_count']} "
        f"({summary['raw_exact_accuracy']:.1%}) "
        f"final 精确={summary['final_correct_count']}/{summary['sample_count']} "
        f"({summary['final_exact_accuracy']:.1%})"
    )
    for record in report["results"]:
        mark = "OK " if record["final_correct"] else "ERR"
        print(f"  [{mark}] {record['sample_id']}: {record['final_latex'] or '<空>'}")
        if not record["final_correct"]:
            print(f"       真值: {record['ground_truth']}")
        if record["error"]:
            print(f"       错误: {record['error']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评估手写公式真值集上的精确匹配准确率")
    parser.add_argument("--manifest", default=str(_DEFAULT_MANIFEST), help="真值清单路径")
    parser.add_argument("--output", help="把完整报告写入该 JSON 文件")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    report = evaluate_handwritten(manifest["samples"])

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"报告已写入 {output_path}")

    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())