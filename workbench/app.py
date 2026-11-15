import hashlib
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from workbench.compiler import compile_tex
from workbench.fix import suggest_fix
from workbench.full_page import build_tex, generate_document, merge_documents


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

logger = logging.getLogger("workbench")
app = FastAPI(title="Hand2LaTeX 智能工作台")
app.mount("/vendor/vue", StaticFiles(directory=_PROJECT_ROOT / "node_modules" / "vue" / "dist"), name="vue")
_JOBS_ROOT.mkdir(parents=True, exist_ok=True)


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


def _job_payload(
    job_id: str,
    directory: Path,
    title: str,
    compile_result: dict,
    page_count: int = 1,
    pages: list[dict] | None = None,
) -> dict:
    return {
        "job_id": job_id,
        "title": title,
        "tex": (directory / "main.tex").read_text(encoding="utf-8"),
        "source_url": f"/api/jobs/{job_id}/source",
        "compile": _public_compile(compile_result, job_id),
        "human_review": True,
        "page_count": page_count,
        "pages": pages or [],
    }


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
    try:
        for page_number, (suffix, content) in enumerate(uploads, start=1):
            page_directory = directory / f"page_{page_number:02d}"
            page_directory.mkdir()
            source_path = page_directory / f"source{suffix}"
            source_path.write_bytes(content)
            document = generate_document(str(source_path))
            (page_directory / "original.tex").write_text(document["tex"], encoding="utf-8")
            (page_directory / "main.tex").write_text(document["tex"], encoding="utf-8")
            documents.append(document)
            pages.append(
                {
                    "page": page_number,
                    "source_url": f"/api/jobs/{job_id}/pages/{page_number}/source",
                    "latency_ms": document["latency_ms"],
                    "human_review": document["human_review"],
                }
            )

        merged = merge_documents(documents)
        merged_tex = build_tex(merged)
        (directory / "original.tex").write_text(merged_tex, encoding="utf-8")
        _write_main_tex(directory, merged_tex)
        compile_result = compile_tex(directory / "main.tex")
    except Exception as error:
        logger.exception("full-page generation failed")
        raise HTTPException(
            status_code=502,
            detail=f"{type(error).__name__}: 整页识别或编译失败，请检查服务配置后重试",
        ) from error
    return _job_payload(
        job_id,
        directory,
        merged["title"],
        compile_result,
        page_count=len(documents),
        pages=pages,
    )


@app.post("/api/documents")
def create_document(images: list[UploadFile] = File(..., alias="image")) -> dict:
    return _create_document(images)


@app.post("/api/documents/batch")
def create_batch_documents(images: list[UploadFile] = File(..., alias="image")) -> dict:
    return _create_document(images)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    directory = _job_dir(job_id)
    return {
        "job_id": job_id,
        "tex": (directory / "main.tex").read_text(encoding="utf-8"),
        "source_url": f"/api/jobs/{job_id}/source",
        "pdf_url": f"/api/jobs/{job_id}/pdf" if (directory / "main.pdf").is_file() else None,
        "human_review": True,
    }


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
    return {"compile": _public_compile(result, job_id), "tex": request.tex}


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
    return {
        "compile": _public_compile(result, job_id),
        "tex": request.tex,
        "summary": request.summary,
    }
