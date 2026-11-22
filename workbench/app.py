import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from workbench.compiler import compile_tex
from workbench.fix import suggest_fix
from workbench.full_page import (
    _attach_figure_sources,
    build_tex,
    generate_document,
    merge_documents,
)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STATIC_ROOT = _PROJECT_ROOT / "workbench" / "static"
_JOBS_ROOT = _PROJECT_ROOT / "artifacts" / "jobs"
_JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_BATCH_IMAGE_BYTES = 50 * 1024 * 1024
_MAX_PAGE_COUNT = 10
_MAX_TEX_CHARS = 200_000
_MAX_LOG_CHARS = 200_000

# 过期 job 清理：默认保留 7 天，可用 WORKBENCH_JOB_MAX_AGE_DAYS 调整（0 = 永不清理）
_JOB_MAX_AGE_SECONDS = float(os.environ.get("WORKBENCH_JOB_MAX_AGE_DAYS", "7")) * 86400.0

logger = logging.getLogger("workbench")
app = FastAPI(title="Hand2LaTeX 智能工作台")
app.mount("/vendor/vue", StaticFiles(directory=_PROJECT_ROOT / "node_modules" / "vue" / "dist"), name="vue")
_JOBS_ROOT.mkdir(parents=True, exist_ok=True)


def _cleanup_expired_jobs(max_age_seconds: float | None = None) -> int:
    """删除超过 max_age 未更新的 job 目录，返回删除数量。

    只碰 artifacts/jobs 下符合 job id 命名（32 位十六进制）的目录，
    其他文件一律不动；单个目录删除失败只记日志，不影响其余清理。
    """
    if max_age_seconds is None:
        max_age_seconds = _JOB_MAX_AGE_SECONDS
    if max_age_seconds <= 0:
        return 0
    removed = 0
    now = time.time()
    try:
        entries = list(_JOBS_ROOT.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_dir() or not _JOB_ID_PATTERN.fullmatch(entry.name):
            continue
        try:
            if now - entry.stat().st_mtime > max_age_seconds:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _start_job_cleanup_scheduler(interval_seconds: float = 24 * 3600.0) -> None:
    """启动每日一次的过期 job 清理线程（守护线程，随进程退出）。"""
    if (os.environ.get("WORKBENCH_JOB_CLEANUP") or "on").strip().lower() in {"off", "0", "false", "no"}:
        return

    def _run() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                removed = _cleanup_expired_jobs()
                if removed:
                    logger.info("已清理 %d 个过期 job 目录", removed)
            except Exception:  # noqa: BLE001 - 清理线程绝不能崩
                logger.exception("job 清理线程异常")

    threading.Thread(target=_run, name="job-cleanup", daemon=True).start()


_cleanup_expired_jobs()
_start_job_cleanup_scheduler()


class CompileRequest(BaseModel):
    tex: str


class FixSuggestionRequest(BaseModel):
    tex: str
    log: str


class ApplyFixRequest(BaseModel):
    tex: str
    summary: str = ""


def _write_main_tex(directory: Path, tex: str) -> None:
    if len(tex) > _MAX_TEX_CHARS:
        raise HTTPException(status_code=400, detail="tex 内容过长")
    history = directory / "history"
    history.mkdir(exist_ok=True)
    (history / f"{uuid.uuid4().hex}.tex").write_text(tex, encoding="utf-8")
    (directory / "main.tex").write_text(tex, encoding="utf-8")


def _sha256_text(tex: str) -> str:
    return hashlib.sha256(tex.encode("utf-8")).hexdigest()


def _job_dir(job_id: str) -> Path:
    if not _JOB_ID_PATTERN.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    directory = _JOBS_ROOT / job_id
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="job not found")
    return directory


def _public_compile(result: dict, job_id: str) -> dict:
    return {
        "success": result["success"],
        "log": result["log"],
        "errors": result["errors"],
        "returncode": result["returncode"],
        "pdf_url": f"/api/jobs/{job_id}/pdf" if result["success"] else None,
    }


def _store_compile(directory: Path, public_result: dict) -> None:
    (directory / "compile.json").write_text(
        json.dumps(public_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _has_figure_blocks(directory: Path) -> bool:
    for document_path in directory.glob("page_*/document.json"):
        try:
            document = json.loads(document_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        blocks = document.get("blocks", [])
        if any(isinstance(block, dict) and block.get("type") == "figure" for block in blocks):
            return True
    return False


def _store_job_metadata(
    directory: Path,
    title: str,
    page_count: int,
    pages: list[dict],
    failures: list[dict],
    *,
    has_figures: bool = False,
) -> None:
    metadata = {
        "title": title,
        "page_count": page_count,
        "pages": pages,
        "has_figures": has_figures,
    }
    if failures:
        metadata["failed_pages"] = failures
    (directory / "job.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_job_title(directory: Path) -> str:
    for name in ("original.tex", "main.tex"):
        path = directory / name
        if not path.is_file():
            continue
        match = re.search(r"\\title\{(.*)\}", path.read_text(encoding="utf-8"))
        if match and match.group(1).strip():
            return match.group(1).strip()
    return "手写笔记"


def _job_metadata(directory: Path) -> dict:
    """读取 job 元数据；老任务没有 job.json 时按目录结构重建。"""
    path = directory / "job.json"
    if path.is_file():
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata.setdefault("title", _read_job_title(directory))
        metadata.setdefault("page_count", 1)
        metadata.setdefault("pages", [])
        metadata.setdefault("has_figures", _has_figure_blocks(directory))
        return metadata

    pages = []
    failures = []
    merged_page = 0
    for page_directory in sorted(directory.glob("page_*")):
        match = re.fullmatch(r"page_(\d+)", page_directory.name)
        if not page_directory.is_dir() or match is None:
            continue
        if not list(page_directory.glob("source.*")):
            continue
        page_number = int(match.group(1))
        succeeded = (page_directory / "main.tex").is_file()
        error = None
        current_merged_page = None
        if succeeded:
            merged_page += 1
            current_merged_page = merged_page
        else:
            error = "该页在之前识别中失败"
            failures.append({"page": page_number, "error": error})
        pages.append(
            {
                "page": page_number,
                "source_url": f"/api/jobs/{directory.name}/pages/{page_number}/source",
                "latency_ms": None,
                "human_review": True,
                "error": error,
                "merged_page": current_merged_page,
            }
        )
    metadata = {
        "title": _read_job_title(directory),
        "page_count": merged_page,
        "pages": pages,
        "has_figures": _has_figure_blocks(directory),
    }
    if failures:
        metadata["failed_pages"] = failures
    return metadata


def _stored_compile(directory: Path, job_id: str) -> dict:
    path = directory / "compile.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    # 老任务没有 compile.json。已有 PDF 时如实说明没有保存日志，避免为了
    # 打开任务又强制跑一遍编译；没有 PDF 时才重新编译以取得真实错误。
    if (directory / "main.pdf").is_file():
        return {
            "success": True,
            "log": "该任务早于编译记录保存，未重新编译；需要最新警告请点“重新排版”。",
            "errors": [],
            "returncode": 0,
            "pdf_url": f"/api/jobs/{job_id}/pdf",
        }
    result = compile_tex(directory / "main.tex")
    public_result = _public_compile(result, job_id)
    _store_compile(directory, public_result)
    return public_result


def _job_payload(
    job_id: str,
    directory: Path,
    title: str,
    compile_result: dict,
    page_count: int = 1,
    pages: list[dict] | None = None,
    failures: list[dict] | None = None,
    has_figures: bool = False,
) -> dict:
    payload = {
        "job_id": job_id,
        "title": title,
        "tex": (directory / "main.tex").read_text(encoding="utf-8"),
        "source_url": f"/api/jobs/{job_id}/source",
        "compile": _public_compile(compile_result, job_id),
        "human_review": True,
        "page_count": page_count,
        "pages": pages or [],
        "has_figures": has_figures,
    }
    if failures:
        payload["failed_pages"] = failures
    return payload


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_STATIC_ROOT / "index.html").read_text(encoding="utf-8")


def _read_image(image: UploadFile) -> tuple[str, bytes]:
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PNG、JPEG、WebP 图片")
    content = image.file.read(_MAX_IMAGE_BYTES + 1)
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 20 MB")
    return suffix, content


def _create_document(images: list[UploadFile]) -> dict:
    if not images or len(images) > _MAX_PAGE_COUNT:
        raise HTTPException(status_code=400, detail="每次上传 1 至 10 页图片")
    uploads = [_read_image(image) for image in images]
    if sum(len(content) for _, content in uploads) > _MAX_BATCH_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="本批图片总大小不能超过 50 MB")

    job_id = uuid.uuid4().hex
    directory = _JOBS_ROOT / job_id
    directory.mkdir()
    documents = []
    pages = []
    failures = []
    try:
        for page_number, (suffix, content) in enumerate(uploads, start=1):
            page_directory = directory / f"page_{page_number:02d}"
            page_directory.mkdir()
            source_path = page_directory / f"source{suffix}"
            source_path.write_bytes(content)
            # 源图先落盘再识别：某页识别失败时，原图与已成功页面都保留下来，
            # 不让第 N 页的失败把前 N-1 页的成果全部丢掉。
            try:
                document = generate_document(str(source_path))
            except Exception as error:
                logger.exception("第 %d 页整页识别失败", page_number)
                message = f"{type(error).__name__}: {error}"
                failures.append({"page": page_number, "error": message})
                pages.append(
                    {
                        "page": page_number,
                        "source_url": f"/api/jobs/{job_id}/pages/{page_number}/source",
                        "latency_ms": None,
                        "human_review": True,
                        "error": message,
                        "merged_page": None,
                    }
                )
                continue
            (page_directory / "original.tex").write_text(document["tex"], encoding="utf-8")
            (page_directory / "main.tex").write_text(document["tex"], encoding="utf-8")
            (page_directory / "document.json").write_text(
                json.dumps(document, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            documents.append(document)
            pages.append(
                {
                    "page": page_number,
                    "source_url": f"/api/jobs/{job_id}/pages/{page_number}/source",
                    "latency_ms": document["latency_ms"],
                    "human_review": document["human_review"],
                    "error": None,
                    "merged_page": len(documents),
                }
            )

        if not documents:
            detail = "；".join(f"第 {f['page']} 页：{f['error']}" for f in failures) or "没有可用页面"
            raise RuntimeError(f"整页识别失败（{detail}），请检查服务配置后重试")

        merged = merge_documents(documents)
        merged_tex = build_tex(merged)
        (directory / "original.tex").write_text(merged_tex, encoding="utf-8")
        _write_main_tex(directory, merged_tex)
        compile_result = compile_tex(directory / "main.tex")
        has_figures = any(
            isinstance(block, dict) and block.get("type") == "figure"
            for document in documents
            for block in document.get("blocks", [])
        )
        _store_job_metadata(
            directory,
            merged["title"],
            len(documents),
            pages,
            failures,
            has_figures=has_figures,
        )
        _store_compile(directory, _public_compile(compile_result, job_id))
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("full-page generation failed")
        raise HTTPException(
            status_code=502,
            detail=f"{type(error).__name__}: 整页识别或编译失败，请检查服务配置后重试",
        ) from error
    payload = _job_payload(
        job_id,
        directory,
        merged["title"],
        compile_result,
        page_count=len(documents),
        pages=pages,
        failures=failures,
        has_figures=has_figures,
    )
    return payload


@app.post("/api/documents")
def create_document(images: list[UploadFile] = File(..., alias="image")) -> dict:
    return _create_document(images)


@app.post("/api/documents/batch")
def create_batch_documents(images: list[UploadFile] = File(..., alias="image")) -> dict:
    return _create_document(images)


@app.get("/api/jobs")
def list_jobs(limit: int = 20, offset: int = 0, q: str = "") -> dict:
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    keyword = q.strip().lower()
    jobs = []
    for entry in _JOBS_ROOT.iterdir():
        if not entry.is_dir() or not _JOB_ID_PATTERN.fullmatch(entry.name):
            continue
        if not (entry / "main.tex").is_file():
            continue
        metadata = _job_metadata(entry)
        if keyword and keyword not in metadata["title"].lower() and keyword not in entry.name:
            continue
        stat = entry.stat()
        jobs.append(
            {
                "job_id": entry.name,
                "title": metadata["title"],
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "page_count": metadata["page_count"],
                "page_total": len(metadata["pages"]),
                "has_pdf": (entry / "main.pdf").is_file(),
                "has_figures": metadata.get("has_figures", False),
                "failed_pages": len(metadata.get("failed_pages", [])),
                "_mtime": stat.st_mtime,
            }
        )
    jobs.sort(key=lambda item: item["_mtime"], reverse=True)
    total = len(jobs)
    page = jobs[offset:offset + limit]
    for job in page:
        job.pop("_mtime", None)
    return {"jobs": page, "total": total, "limit": limit, "offset": offset}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    directory = _job_dir(job_id)
    metadata = _job_metadata(directory)
    return _job_payload(
        job_id,
        directory,
        metadata["title"],
        _stored_compile(directory, job_id),
        page_count=metadata["page_count"],
        pages=metadata["pages"],
        failures=metadata.get("failed_pages"),
        has_figures=metadata.get("has_figures", False),
    )


def _source_paths(directory: Path) -> list[Path]:
    sources = sorted(directory.glob("page_*/source.*"))
    if not sources:
        sources = sorted(directory.glob("source.*"))
    if not sources:
        raise HTTPException(status_code=404, detail="source image not found")
    return sources


@app.get("/api/jobs/{job_id}/source")
def get_source(job_id: str) -> FileResponse:
    return FileResponse(_source_paths(_job_dir(job_id))[0])


@app.get("/api/jobs/{job_id}/pages/{page_number}/source")
def get_page_source(job_id: str, page_number: int) -> FileResponse:
    sources = _source_paths(_job_dir(job_id))
    if page_number < 1 or page_number > len(sources):
        raise HTTPException(status_code=404, detail="page not found")
    return FileResponse(sources[page_number - 1])


@app.get("/api/jobs/{job_id}/pdf")
def get_pdf(job_id: str) -> FileResponse:
    directory = _job_dir(job_id)
    pdf_path = directory / "main.pdf"
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="pdf not found; compile first")
    return FileResponse(pdf_path, media_type="application/pdf")


@app.post("/api/jobs/{job_id}/pages/{page_number}/retry")
def retry_failed_page(job_id: str, page_number: int) -> dict:
    directory = _job_dir(job_id)
    metadata = _job_metadata(directory)
    pages = metadata["pages"]
    entry = next((page for page in pages if page["page"] == page_number), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="page not found")
    if entry.get("error") is None:
        raise HTTPException(status_code=409, detail="这一页已识别成功，无需重试")

    # 重试只重新识别失败页；其他成功页必须已有结构化 document.json，
    # 否则合并时无法保证内容不变。老任务缺文件时明确拒绝，不整批偷偷重跑。
    for page in pages:
        page_directory = directory / f"page_{page['page']:02d}"
        if page.get("error") is None and not (page_directory / "document.json").is_file():
            raise HTTPException(
                status_code=409,
                detail="该任务缺少早期页面结构，不能单页重试；请重新上传整批",
            )

    sources = _source_paths(directory)
    if page_number < 1 or page_number > len(sources):
        raise HTTPException(status_code=404, detail="page not found")
    try:
        document = generate_document(str(sources[page_number - 1]))
    except Exception as error:
        logger.exception("第 %d 页重试识别失败", page_number)
        raise HTTPException(
            status_code=502,
            detail=f"第 {page_number} 页重试失败：{type(error).__name__}: {error}",
        ) from error

    page_directory = directory / f"page_{page_number:02d}"
    (page_directory / "original.tex").write_text(document["tex"], encoding="utf-8")
    (page_directory / "main.tex").write_text(document["tex"], encoding="utf-8")
    (page_directory / "document.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    entry.update(
        error=None,
        latency_ms=document["latency_ms"],
        human_review=document["human_review"],
    )

    documents = []
    for page in sorted(pages, key=lambda item: item["page"]):
        if page.get("error") is not None:
            continue
        document_path = directory / f"page_{page['page']:02d}" / "document.json"
        documents.append(json.loads(document_path.read_text(encoding="utf-8")))

    merged = merge_documents(documents)
    merged_tex = build_tex(merged)
    (directory / "original.tex").write_text(merged_tex, encoding="utf-8")
    _write_main_tex(directory, merged_tex)
    try:
        compile_result = compile_tex(directory / "main.tex")
    except Exception as error:
        logger.exception("retry-page compilation failed")
        raise HTTPException(status_code=500, detail=f"{type(error).__name__}: 重试后编译失败") from error

    merged_page = 0
    failures = []
    for page in sorted(pages, key=lambda item: item["page"]):
        if page.get("error") is not None:
            page["merged_page"] = None
            failures.append({"page": page["page"], "error": page["error"]})
        else:
            merged_page += 1
            page["merged_page"] = merged_page
    has_figures = any(
        isinstance(block, dict) and block.get("type") == "figure"
        for document in documents
        for block in document.get("blocks", [])
    )
    _store_job_metadata(
        directory,
        merged["title"],
        len(documents),
        pages,
        failures,
        has_figures=has_figures,
    )
    _store_compile(directory, _public_compile(compile_result, job_id))
    return _job_payload(
        job_id,
        directory,
        merged["title"],
        compile_result,
        page_count=len(documents),
        pages=pages,
        failures=failures,
        has_figures=has_figures,
    )


@app.post("/api/jobs/{job_id}/figures/use-source")
def use_source_figures(job_id: str) -> dict:
    """把已有任务中的图形块改为嵌入原图，不重新调用识别模型。"""
    directory = _job_dir(job_id)
    metadata = _job_metadata(directory)
    pages = metadata["pages"]
    sources = _source_paths(directory) if pages else []
    documents = []
    found_figure = False
    for page in sorted(pages, key=lambda item: item["page"]):
        if page.get("error") is not None:
            continue
        document_path = directory / f"page_{page['page']:02d}" / "document.json"
        if not document_path.is_file():
            raise HTTPException(
                status_code=409,
                detail="该任务缺少页面结构，无法重建原图；请重新上传整批",
            )
        document = json.loads(document_path.read_text(encoding="utf-8"))
        figure_blocks = [
            block
            for block in document.get("blocks", [])
            if isinstance(block, dict) and block.get("type") == "figure"
        ]
        if figure_blocks:
            if page["page"] > len(sources):
                raise HTTPException(status_code=409, detail="缺少对应页的源图")
            found_figure = True
            _attach_figure_sources(document, str(sources[page["page"] - 1]))
            document_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        documents.append(document)

    if not found_figure:
        raise HTTPException(status_code=409, detail="这个任务没有可保留的图形块")
    merged = merge_documents(documents)
    merged_tex = build_tex(merged)
    if r"\includegraphics" not in merged_tex:
        raise HTTPException(status_code=409, detail="没有适合整页保留原图的图形页")
    (directory / "original.tex").write_text(merged_tex, encoding="utf-8")
    _write_main_tex(directory, merged_tex)
    try:
        compile_result = compile_tex(directory / "main.tex")
    except Exception as error:
        logger.exception("use-source-figures compilation failed")
        raise HTTPException(status_code=500, detail=f"{type(error).__name__}: 原图编译失败") from error

    failures = [
        {"page": page["page"], "error": page["error"]}
        for page in pages
        if page.get("error") is not None
    ]
    _store_job_metadata(
        directory,
        merged["title"],
        len(documents),
        pages,
        failures,
        has_figures=True,
    )
    _store_compile(directory, _public_compile(compile_result, job_id))
    return _job_payload(
        job_id,
        directory,
        merged["title"],
        compile_result,
        page_count=len(documents),
        pages=pages,
        failures=failures,
        has_figures=True,
    )


@app.get("/api/jobs/{job_id}/tex")
def get_tex(job_id: str) -> FileResponse:
    directory = _job_dir(job_id)
    return FileResponse(
        directory / "main.tex",
        media_type="text/plain; charset=utf-8",
        filename=f"hand2latex-{job_id[:8]}.tex",
    )


@app.get("/api/jobs/{job_id}/original")
def get_original_tex(job_id: str) -> FileResponse:
    directory = _job_dir(job_id)
    original_path = directory / "original.tex"
    if not original_path.is_file():
        raise HTTPException(status_code=404, detail="original tex not found")
    return FileResponse(
        original_path,
        media_type="text/plain; charset=utf-8",
        filename=f"hand2latex-{job_id[:8]}-original.tex",
    )


@app.post("/api/jobs/{job_id}/restore-original")
def restore_original_tex(job_id: str) -> dict:
    directory = _job_dir(job_id)
    original_path = directory / "original.tex"
    if not original_path.is_file():
        raise HTTPException(status_code=404, detail="original tex not found")
    original = original_path.read_text(encoding="utf-8")
    _write_main_tex(directory, original)
    (directory / "suggestion.json").unlink(missing_ok=True)
    try:
        result = compile_tex(directory / "main.tex")
    except Exception as error:
        logger.exception("restore-original compilation failed")
        raise HTTPException(status_code=500, detail=f"{type(error).__name__}: 原稿编译失败") from error
    public_result = _public_compile(result, job_id)
    _store_compile(directory, public_result)
    return {"compile": public_result, "tex": original}


@app.post("/api/jobs/{job_id}/compile")
def compile_document(job_id: str, request: CompileRequest) -> dict:
    directory = _job_dir(job_id)
    if not request.tex.strip():
        raise HTTPException(status_code=400, detail="tex 不能为空")
    _write_main_tex(directory, request.tex)
    (directory / "suggestion.json").unlink(missing_ok=True)
    try:
        result = compile_tex(directory / "main.tex")
    except Exception as error:
        logger.exception("document compilation failed")
        raise HTTPException(status_code=500, detail=f"{type(error).__name__}: 编译失败") from error
    public_result = _public_compile(result, job_id)
    _store_compile(directory, public_result)
    return {"compile": public_result, "tex": request.tex}


@app.post("/api/jobs/{job_id}/suggest-fix")
def suggest_document_fix(job_id: str, request: FixSuggestionRequest) -> dict:
    directory = _job_dir(job_id)
    if len(request.log) > _MAX_LOG_CHARS:
        raise HTTPException(status_code=400, detail="编译日志过长")
    original_tex = (directory / "main.tex").read_text(encoding="utf-8")
    if request.tex != original_tex:
        raise HTTPException(status_code=409, detail="源码已变化，请先重新编译")
    try:
        suggestion = suggest_fix(request.tex, request.log)
    except Exception as error:
        logger.exception("fix suggestion failed")
        raise HTTPException(status_code=502, detail=f"{type(error).__name__}: 修复建议生成失败") from error
    suggestion["baseline_sha256"] = _sha256_text(original_tex)
    (directory / "suggestion.json").write_text(
        json.dumps(suggestion, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {**suggestion, "original_tex": original_tex}


@app.post("/api/jobs/{job_id}/apply-fix")
def apply_document_fix(job_id: str, request: ApplyFixRequest) -> dict:
    directory = _job_dir(job_id)
    if not request.tex.strip():
        raise HTTPException(status_code=400, detail="修复后的 tex 不能为空")
    original_tex = (directory / "main.tex").read_text(encoding="utf-8")
    suggestion_path = directory / "suggestion.json"
    if not suggestion_path.is_file():
        raise HTTPException(status_code=409, detail="没有可应用的修复建议")
    suggestion = json.loads(suggestion_path.read_text(encoding="utf-8"))
    if suggestion.get("baseline_sha256") != _sha256_text(original_tex):
        raise HTTPException(status_code=409, detail="源码已变化，请重新生成修复建议")
    (directory / "fix_applied.json").write_text(
        json.dumps(
            {"summary": request.summary, "before": original_tex, "after": request.tex},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_main_tex(directory, request.tex)
    try:
        result = compile_tex(directory / "main.tex")
    except Exception as error:
        logger.exception("fix compilation failed")
        raise HTTPException(
            status_code=500,
            detail={"message": f"{type(error).__name__}: 修复后编译失败", "tex": request.tex},
        ) from error
    public_result = _public_compile(result, job_id)
    _store_compile(directory, public_result)
    return {
        "compile": public_result,
        "tex": request.tex,
        "summary": request.summary,
    }
