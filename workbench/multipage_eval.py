import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from workbench.compiler import compile_tex
from workbench.full_page import _request_page, build_tex, merge_documents


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _error(error: Exception) -> dict:
    return {"type": type(error).__name__, "message": str(error)}


def _document_has_content(document: dict | None) -> bool | None:
    if not isinstance(document, dict) or not isinstance(document.get("blocks"), list):
        return None
    content_keys = {"paragraph": "text", "display_formula": "latex", "figure": "description"}
    for block in document["blocks"]:
        if not isinstance(block, dict):
            return True
        if block.get("type") == "blank_page":
            continue
        key = content_keys.get(block.get("type"))
        if key is None or not isinstance(block.get(key), str) or block[key].strip():
            return True
    return False


def recognize_page(
    page_id: str,
    page: dict,
    cache_dir: Path,
    *,
    offline: bool = False,
    retry_failed: bool = False,
) -> tuple[dict, bool]:
    image_path = Path(page["image"])
    source_sha256 = _sha256(image_path)
    cache_path = cache_dir / f"{page_id}.json"
    if cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        same_source = cached.get("source_sha256") == source_sha256
        reusable_status = cached.get("status") == "success" or (
            not retry_failed and cached.get("status") in {"request_error", "invalid_document"}
        )
        if same_source and reusable_status:
            return cached, True

    base = {
        "page_id": page_id,
        "source_image": str(image_path),
        "source_sha256": source_sha256,
        "model": os.environ.get("OPENAI_MODEL"),
        "human_review": "required",
    }
    if offline:
        return {**base, "status": "offline_cache_miss"}, False

    _write_json(cache_path, {**base, "status": "pending"})
    started = time.perf_counter()
    try:
        document = _request_page(str(image_path))
    except Exception as error:  # noqa: BLE001 - 评估器必须记录每页失败原因并继续跑其余页
        result = {
            **base,
            "status": "request_error",
            "error": _error(error),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        _write_json(cache_path, result)
        return result, False

    raw_document = document
    if page.get("expected_blank") and isinstance(document, dict) and document.get("blocks") == []:
        document = {**document, "blocks": [{"type": "blank_page"}]}
    result = {
        **base,
        "status": "response_saved",
        "document": document,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    if document is not raw_document:
        result["raw_document"] = raw_document
    _write_json(cache_path, result)
    try:
        tex = build_tex(document)
    except (TypeError, ValueError) as error:
        result.update(status="invalid_document", error=_error(error))
        _write_json(cache_path, result)
        return result, False

    result.update(status="success", tex=tex)
    _write_json(cache_path, result)
    return result, False


def _pdf_page_count(pdf_path: Path) -> int:
    with pymupdf.open(pdf_path) as document:
        return document.page_count


def _pdf_last_page_is_blank(pdf_path: Path) -> bool:
    with pymupdf.open(pdf_path) as document:
        page = document[-1]
        text = page.get_text().strip()
        return (not text or text.isdigit()) and not page.get_images() and not page.get_drawings()


def _marker_results(tex: str, pages: list[dict]) -> list[dict]:
    segments = tex.split(r"\newpage")
    results = []
    for index, page in enumerate(pages):
        marker = page.get("marker")
        found = None
        if marker and index < len(segments):
            found = marker in segments[index]
        results.append({"marker": marker, "found_in_expected_segment": found})
    return results


def evaluate_case(
    case: dict,
    pages_by_id: dict,
    cache_dir: Path,
    output_root: Path,
    *,
    offline: bool = False,
    retry_failed: bool = False,
) -> dict:
    case_dir = output_root / case["id"]
    pages = [pages_by_id[page_id] for page_id in case["page_ids"]]
    page_results = []
    documents = []
    api_calls = 0
    cache_hits = 0
    for page_id, page in zip(case["page_ids"], pages):
        result, cache_hit = recognize_page(
            page_id,
            page,
            cache_dir,
            offline=offline,
            retry_failed=retry_failed,
        )
        api_calls += int(not cache_hit and result["status"] != "offline_cache_miss")
        cache_hits += int(cache_hit)
        documents.append(result.get("document"))
        public_result = {
            key: value
            for key, value in result.items()
            if key not in {"document", "raw_document", "tex", "source_sha256"}
        }
        public_result.update(
            cache_hit=cache_hit,
            normalized_empty_blank="raw_document" in result,
            marker=page.get("marker"),
            expected_blank=bool(page.get("expected_blank")),
            blank_page_has_content=(
                _document_has_content(result.get("document")) if page.get("expected_blank") else None
            ),
        )
        page_results.append(public_result)

    result = {
        "case_id": case["id"],
        "description": case.get("description"),
        "page_ids": case["page_ids"],
        "additional_api_calls": api_calls,
        "cache_hits": cache_hits,
        "pages": page_results,
        "transcription_accuracy": None,
        "human_review": "required",
    }
    if any(page["status"] != "success" for page in page_results):
        result.update(status="page_recognition_failed", structural_pass=False)
        _write_json(case_dir / "result.json", result)
        return result

    try:
        merged = merge_documents(documents)
        tex = build_tex(merged)
        _write_json(case_dir / "document.json", merged)
        (case_dir / "main.tex").write_text(tex, encoding="utf-8")
        compile_result = compile_tex(case_dir / "main.tex")
    except (TypeError, ValueError, RuntimeError) as error:
        result.update(status="merge_or_compile_error", structural_pass=False, error=_error(error))
        _write_json(case_dir / "result.json", result)
        return result

    markers = _marker_results(tex, pages)
    page_break_count = tex.count(r"\newpage")
    pdf_path = Path(compile_result["pdf_path"]) if compile_result["success"] else None
    pdf_page_count = _pdf_page_count(pdf_path) if pdf_path else None
    trailing_blank_expected = bool(pages[-1].get("expected_blank"))
    trailing_blank_pdf_is_blank = (
        _pdf_last_page_is_blank(pdf_path) if pdf_path and trailing_blank_expected else None
    )
    blank_pages_faithful = all(
        page["blank_page_has_content"] is False
        for page in page_results
        if page["expected_blank"]
    )
    structural_pass = (
        page_break_count == len(pages) - 1
        and all(item["found_in_expected_segment"] is not False for item in markers)
        and blank_pages_faithful
        and compile_result["success"]
        and pdf_page_count is not None
        and pdf_page_count >= len(pages)
        and (not trailing_blank_expected or trailing_blank_pdf_is_blank is True)
    )
    result.update(
        status="compiled" if compile_result["success"] else "compile_failed",
        structural_pass=structural_pass,
        page_break_count=page_break_count,
        expected_page_break_count=len(pages) - 1,
        markers=markers,
        blank_pages_faithful=blank_pages_faithful,
        trailing_blank_pdf_is_blank=trailing_blank_pdf_is_blank,
        compile=compile_result,
        pdf_page_count=pdf_page_count,
        source_page_count=len(pages),
        pdf_page_count_note="A source page may occupy multiple PDF pages when recognized content overflows.",
    )
    _write_json(case_dir / "result.json", result)
    return result


def run_evaluation(
    manifest_path: str | Path,
    output_root: str | Path,
    *,
    offline: bool = False,
    retry_failed: bool = False,
) -> dict:
    manifest_path = Path(manifest_path)
    output_root = Path(output_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages_by_id = manifest["pages"]
    cache_dir = output_root / "cache" / "pages"
    results = []
    report = {
        "sample_type": manifest["sample_type"],
        "evaluation_scope": manifest["evaluation_scope"],
        "transcription_accuracy": manifest["transcription_accuracy"],
        "method": (
            "offline_replay_of_saved_page_results_with_local_tectonic"
            if offline
            else "real_api_with_saved_page_response_reuse_and_local_tectonic"
        ),
        "execution_mode": "offline" if offline else "real_api_and_cache",
        "retry_failed": retry_failed,
        "manifest": str(manifest_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "results": results,
    }
    _write_json(output_root / "report.json", report)
    for case in manifest["cases"]:
        results.append(
            evaluate_case(
                case,
                pages_by_id,
                cache_dir,
                output_root,
                offline=offline,
                retry_failed=retry_failed,
            )
        )
        _write_json(output_root / "report.json", report)

    cached_page_statuses = [
        page["status"]
        for result in results
        for page in result["pages"]
        if page["cache_hit"]
    ]
    report.update(
        status="complete",
        completed_at=datetime.now(timezone.utc).isoformat(),
        additional_api_calls=sum(result["additional_api_calls"] for result in results),
        cache_hits=len(cached_page_statuses),
        successful_cache_hits=cached_page_statuses.count("success"),
        failed_cache_hits=sum(status != "success" for status in cached_page_statuses),
        cases_total=len(results),
        cases_structurally_passed=sum(result["structural_pass"] for result in results),
        latency_note="Cached page latency_ms is historical request time, not a new per-case speed measurement.",
        accuracy_note="Structural success does not establish exact transcription or mathematical correctness.",
    )
    _write_json(output_root / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate real multipage handwriting samples with cached page responses.")
    parser.add_argument("--manifest", default="data/multipage_samples.json")
    parser.add_argument("--output", default="artifacts/multipage_real")
    parser.add_argument("--offline", action="store_true", help="Reuse saved responses without new API calls.")
    parser.add_argument("--retry-failed", action="store_true", help="Request pages whose cached terminal status is an error.")
    args = parser.parse_args()
    report = run_evaluation(
        args.manifest,
        args.output,
        offline=args.offline,
        retry_failed=args.retry_failed,
    )
    summary = {
        "status": report["status"],
        "execution_mode": report["execution_mode"],
        "additional_api_calls": report["additional_api_calls"],
        "cache_hits": report["cache_hits"],
        "successful_cache_hits": report["successful_cache_hits"],
        "failed_cache_hits": report["failed_cache_hits"],
        "cases_total": report["cases_total"],
        "cases_structurally_passed": report["cases_structurally_passed"],
        "cases": [
            {
                "case_id": result["case_id"],
                "status": result["status"],
                "structural_pass": result["structural_pass"],
                "pdf_page_count": result.get("pdf_page_count"),
            }
            for result in report["results"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
