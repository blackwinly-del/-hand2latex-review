import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from workbench.compiler import _find_tectonic, compile_tex
from workbench.fix import suggest_fix
from workbench.full_page import (
    _attach_figure_sources,
    _ctex_fontset,
    build_tex,
    generate_document,
    merge_documents,
)
from workbench.version import VERSION


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STATIC_ROOT = _PROJECT_ROOT / "workbench" / "static"
_JOBS_ROOT = _PROJECT_ROOT / "artifacts" / "jobs"
_JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")
_HISTORY_NAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.tex$")
_SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_BATCH_IMAGE_BYTES = 50 * 1024 * 1024
_MAX_PAGE_COUNT = 10
_MAX_TEX_CHARS = 200_000
_MAX_LOG_CHARS = 200_000
_BUILD_INFO_PATH = _PROJECT_ROOT / "BUILD_INFO.json"

# 过期 job 清理：默认保留 7 天，可用 WORKBENCH_JOB_MAX_AGE_DAYS 调整（0 = 永不清理）
_JOB_MAX_AGE_SECONDS = float(os.environ.get("WORKBENCH_JOB_MAX_AGE_DAYS", "7")) * 86400.0

logger = logging.getLogger("workbench")
app = FastAPI(title="Hand2LaTeX 智能工作台")


def _vue_asset_dir() -> tuple[Path | None, str | None]:
    """定位 Vue 全局构建：开发仓库用 node_modules，安装包用随包携带的副本。"""
    candidates = (
        (_PROJECT_ROOT / "node_modules" / "vue" / "dist", "node_modules（npm install 装的）"),
        (_STATIC_ROOT / "vendor" / "vue", "随安装包携带的副本"),
    )
    for directory, source in candidates:
        if (directory / "vue.global.js").is_file():
            return directory, source
    return None, None


_VUE_DIR, _VUE_SOURCE = _vue_asset_dir()
if _VUE_DIR is not None:
    app.mount("/vendor/vue", StaticFiles(directory=_VUE_DIR), name="vue")
else:
    logger.warning(
        "找不到 vue.global.js，网页会白屏：请运行 npm install，"
        "或把 vue.global.js 放到 workbench/static/vendor/vue/"
    )
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


class RestoreHistoryRequest(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# 运行进度：整页识别一次要几十秒到几分钟，前端需要知道"现在卡在哪一页"。
# 只记录真实发生的状态（排队/识别中/完成/失败、开始与结束时间、耗时），
# 不估算剩余时间，也不给任何"可信度分数"。
# ---------------------------------------------------------------------------
_RUNS_LOCK = threading.Lock()
_RUNS: dict[str, dict] = {}
_MAX_STORED_RUNS = 20


# ---------------------------------------------------------------------------
# 按任务粒度的写锁
#
# 同一个 job 的 main.tex 可能被多个请求同时改写（重新排版、恢复历史版本、
# 应用 AI 修复、恢复原稿、图形页改用原图）。这些路径都会"读当前 tex → 写新 tex
# → 编译 → 落 compile.json"。两个请求交错执行时，后写的会把先写的内容顶掉，
# 而两个请求都返回 200 成功——先到的那个拿到的是假成功，用户看到的现象是
# "点了重新排版，PDF 却变成别的版本"，且没有任何报错。
#
# 这里用"每个 job 一把锁"把这一整段串起来。锁的创建本身要加元锁，
# 否则两个线程可能同时给同一个 job 造出两把不同的锁，等于没锁。
# ---------------------------------------------------------------------------
_JOB_WRITE_LOCKS: dict[str, threading.Lock] = {}
_JOB_WRITE_LOCKS_GUARD = threading.Lock()


def _job_write_lock(job_id: str) -> threading.Lock:
    with _JOB_WRITE_LOCKS_GUARD:
        lock = _JOB_WRITE_LOCKS.get(job_id)
        if lock is None:
            lock = threading.Lock()
            _JOB_WRITE_LOCKS[job_id] = lock
        return lock


def _page_concurrency(page_count: int) -> int:
    """整页识别的并发页数。每页是一次独立的云端请求，可以并行等待。"""
    raw = os.environ.get("WORKBENCH_PAGE_CONCURRENCY", "3")
    try:
        configured = int(raw)
    except ValueError:
        configured = 3
    configured = max(1, min(configured, _MAX_PAGE_COUNT))
    return min(configured, max(1, page_count))


def _new_run(run_id: str, total_pages: int) -> None:
    concurrency = _page_concurrency(total_pages)
    run = {
        "run_id": run_id,
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "job_id": None,
        "error": None,
        "total_pages": total_pages,
        "concurrency": concurrency,
        "pages": [
            {
                "page": number,
                "state": "pending",
                "started_at": None,
                "finished_at": None,
                "latency_ms": None,
                "retried": None,
                "error": None,
            }
            for number in range(1, total_pages + 1)
        ],
    }
    with _RUNS_LOCK:
        _RUNS[run_id] = run
        if len(_RUNS) > _MAX_STORED_RUNS:
            for key in sorted(_RUNS, key=lambda item: _RUNS[item]["started_at"])[: len(_RUNS) - _MAX_STORED_RUNS]:
                _RUNS.pop(key, None)


def _set_page_state(run_id: str, page_number: int, **fields) -> None:
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return
        for page in run["pages"]:
            if page["page"] == page_number:
                page.update(fields)
                return


def _finish_run(run_id: str, status: str, *, job_id: str | None = None, error: str | None = None) -> None:
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return
        run.update(status=status, finished_at=time.time(), job_id=job_id, error=error)


def _run_snapshot(run_id: str) -> dict | None:
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return None
        snapshot = json.loads(json.dumps(run))
    finished = snapshot["finished_at"] or time.time()
    snapshot["elapsed_ms"] = round((finished - snapshot["started_at"]) * 1000)
    snapshot["done_pages"] = sum(1 for page in snapshot["pages"] if page["state"] in {"done", "failed"})
    snapshot["running_pages"] = [page["page"] for page in snapshot["pages"] if page["state"] == "running"]
    return snapshot


# ---------------------------------------------------------------------------
# 系统状态：只报告能当场核对的事实（文件在不在、配置有没有填、编译器能不能跑）。
# ---------------------------------------------------------------------------
_STATUS_LOCK = threading.Lock()
_STATUS_CACHE: dict[str, tuple[float, object]] = {}
_STATUS_CACHE_SECONDS = 30.0


def _cached_status(key: str, producer):
    """状态接口会被前端轮询，子进程探测与目录统计按 30 秒缓存。"""
    now = time.time()
    with _STATUS_LOCK:
        entry = _STATUS_CACHE.get(key)
        if entry is not None and now - entry[0] < _STATUS_CACHE_SECONDS:
            return entry[1]
    value = producer()
    with _STATUS_LOCK:
        _STATUS_CACHE[key] = (now, value)
    return value


def _build_info() -> dict:
    """安装包会写入 BUILD_INFO.json；开发仓库则如实报告 git 短提交号。

    BUILD_INFO.json 是打包产物，只该存在于安装包/绿色包里。它在 git 历史里待过一段时间，
    于是开发仓库里也留着一份（内容永远是上一次打包的 commit 与 built_at），
    而这里原先只看"文件在不在"就报 source=安装包 —— 开发仓库的 /api/status 因此会
    显示一个早就过期的提交号，排查时会被引到错误方向。
    判据改成：仓库里有 .git 就是开发仓库（打包会排除 .git），此时一律以 git 为准。
    """
    is_dev_checkout = (_PROJECT_ROOT / ".git").exists()
    if not is_dev_checkout and _BUILD_INFO_PATH.is_file():
        try:
            # Windows 上写出来的 JSON 可能带 BOM，用 utf-8-sig 才读得动。
            info = json.loads(_BUILD_INFO_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            info = None
        if isinstance(info, dict):
            return {"source": "安装包", "version": VERSION, "commit": None, "built_at": None, **info}
    commit = None
    if is_dev_checkout:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            if completed.returncode == 0:
                commit = completed.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            commit = None
    return {"source": "开发仓库", "version": VERSION, "commit": commit, "built_at": None}


def _tectonic_status() -> dict:
    def probe() -> dict:
        path = _find_tectonic()
        if path is None:
            return {"available": False, "path": None, "version": None}
        try:
            completed = subprocess.run(
                [str(path), "--version"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {"available": True, "path": str(path), "version": None}
        output = (completed.stdout or "") + (completed.stderr or "")
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return {"available": True, "path": str(path), "version": lines[0] if lines else None}

    return _cached_status("tectonic", probe)


def _jobs_status() -> dict:
    def probe() -> dict:
        count = 0
        total_bytes = 0
        try:
            entries = list(_JOBS_ROOT.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_dir() or not _JOB_ID_PATTERN.fullmatch(entry.name):
                continue
            count += 1
            for path in entry.rglob("*"):
                try:
                    if path.is_file():
                        total_bytes += path.stat().st_size
                except OSError:
                    continue
        return {"count": count, "total_bytes": total_bytes, "directory": str(_JOBS_ROOT)}

    return _cached_status("jobs", probe)


def _recognizer_status() -> dict:
    """本地公式后端的配置事实。整页识别走云端多模态模型，这里只说明配置。"""
    models_root = _PROJECT_ROOT / "models"
    local_models = []
    if models_root.is_dir():
        for entry in sorted(models_root.iterdir()):
            try:
                if entry.is_dir() and (entry / "inference.json").is_file():
                    local_models.append(entry.name)
            except OSError:
                continue
    return {
        "model": (os.environ.get("RECOGNIZER_MODEL") or "").strip() or None,
        "device": (os.environ.get("RECOGNIZER_DEVICE") or "").strip() or None,
        "model_dir": (os.environ.get("RECOGNIZER_MODEL_DIR") or "").strip() or None,
        "local_models": local_models,
        "used_by": "画板与单公式识别；整页识别使用云端多模态模型，不调用本地公式模型",
    }


def _openai_status() -> dict:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    return {
        "configured": bool(api_key),
        "key_length": len(api_key) or None,
        "model": (os.environ.get("OPENAI_MODEL") or "").strip() or None,
        "base_url": (os.environ.get("OPENAI_BASE_URL") or "").strip() or None,
        "timeout_seconds": os.environ.get("FULLPAGE_TIMEOUT_SECONDS", "120"),
        "max_tokens": os.environ.get("FULLPAGE_MAX_TOKENS", "24000"),
    }


def _python_runtime() -> dict:
    """当前是哪个 Python 在跑：安装包随带的运行时，还是本机自己的环境。"""
    executable = Path(sys.executable)
    try:
        resolved = executable.resolve()
    except OSError:
        resolved = executable
    try:
        bundled_root = (_PROJECT_ROOT / "runtime").resolve()
    except OSError:
        bundled_root = _PROJECT_ROOT / "runtime"
    is_bundled = bundled_root in resolved.parents
    return {
        "executable": str(resolved),
        "bundled": is_bundled,
        "source": "安装包随带的 Python 运行时（本机没装 Python 也能跑）" if is_bundled else "本机自己的 Python 环境",
        "in_virtualenv": sys.prefix != sys.base_prefix,
    }


def _status_checks(openai_status: dict, tectonic: dict, fontset: str | None, fontset_error: str | None) -> list[dict]:
    """把上面的事实翻译成"能用/要注意/不能用"，每条都说明依据。"""
    checks = []
    if openai_status["configured"] and openai_status["model"]:
        checks.append(
            {
                "id": "openai",
                "label": "云端整页识别",
                "level": "ok",
                "detail": f"已配置模型 {openai_status['model']}（密钥长度 {openai_status['key_length']}，不显示内容）",
            }
        )
    elif openai_status["configured"]:
        checks.append({"id": "openai", "label": "云端整页识别", "level": "warn", "detail": "密钥已填，但 OPENAI_MODEL 为空，识别会失败"})
    else:
        checks.append({"id": "openai", "label": "云端整页识别", "level": "bad", "detail": "OPENAI_API_KEY 未配置：上传识别、修复建议都用不了"})
    if not openai_status["base_url"]:
        checks.append({"id": "base_url", "label": "接口地址", "level": "warn", "detail": "OPENAI_BASE_URL 未设置，将直连 OpenAI 官方接口（国内网络通常连不上）"})
    if tectonic["available"]:
        checks.append({"id": "tectonic", "label": "PDF 编译器", "level": "ok", "detail": tectonic["version"] or tectonic["path"]})
    else:
        checks.append({"id": "tectonic", "label": "PDF 编译器", "level": "bad", "detail": "找不到 Tectonic：能识别和改代码，但排不出 PDF"})
    if fontset_error:
        checks.append({"id": "fontset", "label": "中文字体配置", "level": "bad", "detail": fontset_error})
    else:
        checks.append({"id": "fontset", "label": "中文字体配置", "level": "ok", "detail": f"ctex fontset={fontset}"})
    if _VUE_DIR is not None:
        checks.append({"id": "frontend", "label": "网页前端资源", "level": "ok", "detail": f"vue.global.js 来自{_VUE_SOURCE}"})
    else:
        checks.append(
            {
                "id": "frontend",
                "label": "网页前端资源",
                "level": "bad",
                "detail": "找不到 vue.global.js：打开网页会白屏。运行 npm install，或把该文件放到 workbench/static/vendor/vue/",
            }
        )
    return checks


class FixSuggestionRequest(BaseModel):
    tex: str
    log: str


class ApplyFixRequest(BaseModel):
    tex: str
    summary: str = ""


class ReviewRequest(BaseModel):
    """复核状态：page -> 是否已核对。

    page 用字符串键（JSON 对象的键本来就是字符串），值只接受布尔。
    允许一次提交多页，因为前端是整份状态一起存的；也允许只传一页。
    """

    pages: dict[str, bool]


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
        # 结构化诊断：带行号、上下文片段、缺字码位。
        # errors 保持原样不动（老前端、老测试都按 line/message 两键断言过），
        # 新字段只做增量，前端读到就用、读不到就回退到扫 log。
        "diagnostics": result.get("diagnostics", []),
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


def _read_job_json(directory: Path) -> dict:
    """读 job.json 原始内容；不存在或坏了都返回空 dict（不抛异常）。"""
    path = directory / "job.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


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
    # 复核进度必须原地保留。这个函数是"整份重写 job.json"，而重试单页
    # （/retry）、图形页换原图（/figures/use-source）都会再调一次。如果不
    # 把用户已经标过的页面搬回来，用户核对到第 8 页、去重试一个失败页，
    # 回来发现 8 个对勾全没了——这是比"没保存"更让人恼火的行为。
    previous = _read_job_json(directory)
    if previous and isinstance(previous.get("reviewed_pages"), dict):
        metadata["reviewed_pages"] = previous["reviewed_pages"]
        if previous.get("reviewed_updated_at"):
            metadata["reviewed_updated_at"] = previous["reviewed_updated_at"]
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
        # 这里不能用 d.setdefault(key, 昂贵函数())。setdefault 的默认值参数
        # 是**先求值再传进去**的，键已存在也照样算一遍：
        #   metadata.setdefault("has_figures", _has_figure_blocks(directory))
        # 会对每个任务都 glob 一遍 page_*/document.json 并解析，即使 job.json
        # 里已经写了 has_figures。实测 300 个任务时 /api/jobs 要 2.2 秒，
        # 其中这一行占 61%（见下面的计时）。改成键缺失时才算。
        if "title" not in metadata:
            metadata["title"] = _read_job_title(directory)
        metadata.setdefault("page_count", 1)
        metadata.setdefault("pages", [])
        if "has_figures" not in metadata:
            metadata["has_figures"] = _has_figure_blocks(directory)
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
            "diagnostics": [],
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
    # 复核进度跟任务一起返回，前端打开任务就能恢复对勾，不必等额外一次请求。
    # 没有这个字段时返回空对象（不是 null），前端可以直接展开而不用判空。
    stored = _read_job_json(directory)
    reviewed = stored.get("reviewed_pages")
    if isinstance(reviewed, dict):
        payload["reviewed_pages"] = {str(page): True for page in reviewed if str(page).strip()}
        payload["reviewed_updated_at"] = stored.get("reviewed_updated_at")
    else:
        payload["reviewed_pages"] = {}
    return payload


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_STATIC_ROOT / "index.html").read_text(encoding="utf-8")


class _AllPagesFailed(Exception):
    """所有页都没识别出来。和"服务配置坏了"区分开，便于返回 422 而不是 502。"""


def _sniff_image_suffix(content: bytes) -> str | None:
    """按文件头判断真实图片格式，认不出来返回 None。

    只看扩展名是不够的：把文本文件改名成 .png 能混过扩展名校验，然后一路走到
    识别阶段才失败，最后抛出的是"整页识别或编译失败，请检查服务配置"——用户会
    被引去查密钥和编译器，而真实原因只是这个文件不是图片。这里提前拦掉，
    给一句能看懂的话。
    """
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    # JPEG 以 FF D8 FF 开头；SOI 后面紧跟的 marker 可能是 E0/E1/DB/EE 等，不逐一枚举。
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    # WebP 是 RIFF 容器：0-3 是 "RIFF"，8-11 必须是 "WEBP"。
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


def _read_image(image: UploadFile) -> tuple[str, bytes]:
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PNG、JPEG、WebP 图片")
    content = image.file.read(_MAX_IMAGE_BYTES + 1)
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 20 MB")
    if not content:
        raise HTTPException(status_code=400, detail=f"文件是空的（{image.filename or '未命名'}），请重新导出后再上传")
    sniffed = _sniff_image_suffix(content)
    if sniffed is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"这不是有效的图片文件（{image.filename or '未命名'}）："
                "内容是 PNG / JPEG / WebP 之外的格式。"
                "如果它是 HEIC、PDF 或截图工具的特殊格式，请先另存为 PNG 再上传。"
            ),
        )
    # 以文件头的真实格式为准落盘，避免"扩展名 .png 但实际是 JPEG"这种错配。
    return sniffed, content


def _create_document(images: list[UploadFile], run_id: str = "") -> dict:
    if not images or len(images) > _MAX_PAGE_COUNT:
        raise HTTPException(status_code=400, detail="每次上传 1 至 10 页图片")
    uploads = [_read_image(image) for image in images]
    if sum(len(content) for _, content in uploads) > _MAX_BATCH_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="本批图片总大小不能超过 50 MB")

    job_id = uuid.uuid4().hex
    directory = _JOBS_ROOT / job_id
    directory.mkdir()
    candidate_run_id = run_id.strip().lower()
    run_key = candidate_run_id if _RUN_ID_PATTERN.fullmatch(candidate_run_id) else job_id
    _new_run(run_key, len(uploads))

    # 从这里开始目录已经建出来了。后面任何一步整体失败（比如所有页都没识别出来）
    # 都会留下一个只有源图、没有 main.tex 的空任务，既占磁盘又会被任务列表扫到。
    # 所以统一兜底：失败时把没建成的目录删掉（_discard_job_directory 自己会
    # 检查 main.tex 是否存在，已写出代码的任务不会被误删）。
    try:
        return _build_document(uploads, directory, job_id, run_key)
    except BaseException:
        _discard_job_directory(directory)
        raise


def _discard_job_directory(directory: Path) -> None:
    """删掉一个没成功建起来的任务目录。

    只在"目录里还没有 main.tex"时动手：万一失败发生在很靠后的位置
    （例如 compile 抛错但 tex 已经写好），那个任务至少有代码可看，
    不该被当成垃圾删掉。
    """
    try:
        if (directory / "main.tex").is_file():
            return
        shutil.rmtree(directory, ignore_errors=True)
    except OSError:
        logger.warning("清理失败的上传目录时出错：%s", directory, exc_info=True)


def _build_document(
    uploads: list[tuple[str, bytes]],
    directory: Path,
    job_id: str,
    run_key: str,
) -> dict:
    # 源图先全部落盘再识别：某页识别失败时，原图与已成功页面都保留下来，
    # 不让第 N 页的失败把前 N-1 页的成果全部丢掉。
    source_paths: list[Path] = []
    for page_number, (suffix, content) in enumerate(uploads, start=1):
        page_directory = directory / f"page_{page_number:02d}"
        page_directory.mkdir()
        source_path = page_directory / f"source{suffix}"
        source_path.write_bytes(content)
        source_paths.append(source_path)

    results: list[dict | None] = [None] * len(uploads)
    page_errors: dict[int, str] = {}

    def recognize(page_number: int) -> None:
        _set_page_state(run_key, page_number, state="running", started_at=time.time())
        try:
            document = generate_document(str(source_paths[page_number - 1]))
        except Exception as error:  # noqa: BLE001 - 单页失败要记录下来，其余页继续
            logger.exception("第 %d 页整页识别失败", page_number)
            message = f"{type(error).__name__}: {error}"
            page_errors[page_number] = message
            _set_page_state(run_key, page_number, state="failed", finished_at=time.time(), error=message)
            return
        signals = document.get("signals") or {}
        results[page_number - 1] = document
        _set_page_state(
            run_key,
            page_number,
            state="done",
            finished_at=time.time(),
            latency_ms=document.get("latency_ms"),
            retried=signals.get("retried"),
        )

    # 每页是一次独立的云端请求，串行等待会把多页任务的耗时按页数放大。
    concurrency = _page_concurrency(len(uploads))
    if concurrency <= 1:
        for page_number in range(1, len(uploads) + 1):
            recognize(page_number)
    else:
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="page") as pool:
            list(pool.map(recognize, range(1, len(uploads) + 1)))

    documents = []
    pages = []
    failures = []
    has_figures = False
    try:
        for page_number, document in enumerate(results, start=1):
            page_directory = directory / f"page_{page_number:02d}"
            if document is None:
                message = page_errors.get(page_number, "该页识别失败")
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
            if any(
                isinstance(block, dict) and block.get("type") == "figure"
                for block in document.get("blocks", [])
            ):
                has_figures = True
            pages.append(
                {
                    "page": page_number,
                    "source_url": f"/api/jobs/{job_id}/pages/{page_number}/source",
                    "latency_ms": document["latency_ms"],
                    "human_review": document["human_review"],
                    "error": None,
                    "merged_page": len(documents),
                    "signals": document.get("signals"),
                }
            )

        if not documents:
            detail = "；".join(f"第 {f['page']} 页：{f['error']}" for f in failures) or "没有可用页面"
            # 这是"这次上传本身没成功"，不是服务配置坏了。用 422 + 逐页原因，
            # 让界面能直接显示"第几页失败、为什么"，而不是一句笼统的 502。
            raise _AllPagesFailed(f"每一页都没能识别出来。{detail}")

        merged = merge_documents(documents)
        merged_tex = build_tex(merged)
        (directory / "original.tex").write_text(merged_tex, encoding="utf-8")
        _write_main_tex(directory, merged_tex)
        compile_result = compile_tex(directory / "main.tex")
        _store_job_metadata(
            directory,
            merged["title"],
            len(documents),
            pages,
            failures,
            has_figures=has_figures,
        )
        _store_compile(directory, _public_compile(compile_result, job_id))
    except _AllPagesFailed as error:
        _finish_run(run_key, "failed", error=str(error))
        raise HTTPException(status_code=422, detail=str(error)) from error
    except HTTPException as error:
        _finish_run(run_key, "failed", error=error.detail)
        raise
    except Exception as error:
        logger.exception("full-page generation failed")
        _finish_run(run_key, "failed", error=f"{type(error).__name__}: {error}")
        raise HTTPException(
            status_code=502,
            detail=f"{type(error).__name__}: 整页识别或编译失败，请检查服务配置后重试",
        ) from error
    _finish_run(run_key, "done", job_id=job_id)
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
    payload["run_id"] = run_key
    return payload


@app.post("/api/documents")
def create_document(
    images: list[UploadFile] = File(..., alias="image"),
    run_id: str = Form(""),
) -> dict:
    return _create_document(images, run_id)


@app.post("/api/documents/batch")
def create_batch_documents(
    images: list[UploadFile] = File(..., alias="image"),
    run_id: str = Form(""),
) -> dict:
    return _create_document(images, run_id)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """查询一次上传的实时进度。只在本进程内存里，服务重启后不再保留。"""
    key = run_id.strip().lower()
    if not _RUN_ID_PATTERN.fullmatch(key):
        raise HTTPException(status_code=404, detail="run not found")
    snapshot = _run_snapshot(key)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")
    return snapshot


@app.get("/api/status")
def get_status() -> dict:
    """工作台自检：把"这台机器上到底能不能跑通"如实列出来。"""
    openai_status = _openai_status()
    tectonic = _tectonic_status()
    try:
        fontset = _ctex_fontset()
        fontset_error = None
    except RuntimeError as error:
        fontset = None
        fontset_error = str(error)
    return {
        "version": VERSION,
        "build": _build_info(),
        "python": platform.python_version(),
        "python_runtime": _python_runtime(),
        "platform": platform.platform(),
        "openai": openai_status,
        "tectonic": tectonic,
        "fontset": fontset,
        "recognizer": _recognizer_status(),
        "page_concurrency": _page_concurrency(_MAX_PAGE_COUNT),
        "frontend": {"available": _VUE_DIR is not None, "source": _VUE_SOURCE, "path": str(_VUE_DIR) if _VUE_DIR else None},
        "jobs": _jobs_status(),
        "checks": _status_checks(openai_status, tectonic, fontset, fontset_error),
    }


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


@app.post("/api/jobs/{job_id}/review")
def save_review_state(job_id: str, request: ReviewRequest) -> dict:
    """保存"哪几页已经对照原图核对过"。

    为什么必须存在服务端：原先这份状态只写在浏览器 localStorage 里
    （前端 `hand2latex:reviewed:<id>`）。做多页笔记的人是"今天核对 8 页、
    明天接着核剩下 2 页"，但换一台机器、换一个浏览器、或者清一次缓存，
    对勾就全没了，而且没有任何提示。任务本身在服务端，进度却在浏览器，
    这个状态的寿命比它描述的东西还短，是不合理的。

    写入仍然保留 localStorage：断网或后端是旧版时，前端还能退回到本机记录，
    不会因为接口 404 就把界面卡住。
    """
    directory = _job_dir(job_id)
    # 与 apply-fix / restore-history / retry 等写接口共用同一把每任务锁：
    # 它们都会整份重写 job.json，不串起来的话，复核提交可能把刚写好的
    # pages 列表顶掉，或者反过来被顶掉。
    with _job_write_lock(job_id):
        metadata = _read_job_json(directory)
        reviewed = metadata.get("reviewed_pages")
        if not isinstance(reviewed, dict):
            reviewed = {}
        page_count = metadata.get("page_count")
        changed = 0
        for raw_page, raw_value in request.pages.items():
            try:
                page = int(str(raw_page).strip())
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"页号不合法：{raw_page}") from None
            if page < 1:
                raise HTTPException(status_code=400, detail=f"页号不合法：{raw_page}")
            # 页号落在任务实际页数之外说明前端状态串了（比如换了任务没清干净）。
            # 直接拒掉，避免 job.json 里积累一堆不存在的页号。
            if isinstance(page_count, int) and page_count >= 1 and page > page_count:
                raise HTTPException(
                    status_code=400,
                    detail=f"页号超出范围：第 {page} 页，本任务共 {page_count} 页",
                )
            key = str(page)
            # 只存 True。没核对的页直接删掉键，而不是存 false——这样 job.json
            # 里只留真正核对过的页，看文件就知道进度，也不会随页数无限增长。
            if raw_value:
                if reviewed.get(key) is not True:
                    reviewed[key] = True
                    changed += 1
            elif key in reviewed:
                del reviewed[key]
                changed += 1
        metadata["reviewed_pages"] = reviewed
        if changed:
            metadata["reviewed_updated_at"] = datetime.now(tz=timezone.utc).isoformat()
            (directory / "job.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    pages = sorted(int(key) for key in reviewed)
    return {
        "job_id": job_id,
        "reviewed_pages": {str(page): True for page in pages},
        "reviewed_count": len(pages),
        "changed": changed,
        "updated_at": metadata.get("reviewed_updated_at"),
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
        signals=document.get("signals"),
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
    # 这个接口会重写 page_*/document.json 和 main.tex，必须和编译/恢复互斥。
    with _job_write_lock(job_id):
        return _use_source_figures_locked(job_id, directory)


def _use_source_figures_locked(job_id: str, directory: Path) -> dict:
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
    with _job_write_lock(job_id):
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
    # 整个"读旧 tex → 判断能否复用 → 写新 tex → 编译 → 落盘"要在同一把锁里。
    # 只锁写的那一行没用：两个请求会同时判定"需要重新编译"，然后各编译一遍，
    # 后落盘的顶掉先落盘的，而两个都返回成功。
    with _job_write_lock(job_id):
        return _compile_locked(job_id, directory, request.tex)


def _compile_locked(job_id: str, directory: Path, tex: str) -> dict:
    main_tex = directory / "main.tex"
    # 代码没变、PDF 和编译记录都还在时直接复用上次结果：Tectonic 一次要十几秒，
    # 重复点"重新排版"不应该再等一遍。
    if (
        main_tex.is_file()
        and (directory / "main.pdf").is_file()
        and (directory / "compile.json").is_file()
        and main_tex.read_text(encoding="utf-8") == tex
    ):
        stored = _stored_compile(directory, job_id)
        (directory / "suggestion.json").unlink(missing_ok=True)
        return {"compile": stored, "tex": tex, "reused": True}
    _write_main_tex(directory, tex)
    (directory / "suggestion.json").unlink(missing_ok=True)
    try:
        result = compile_tex(directory / "main.tex")
    except Exception as error:
        logger.exception("document compilation failed")
        raise HTTPException(status_code=500, detail=f"{type(error).__name__}: 编译失败") from error
    public_result = _public_compile(result, job_id)
    _store_compile(directory, public_result)
    return {"compile": public_result, "tex": tex}


@app.get("/api/jobs/{job_id}/history")
def list_history(job_id: str) -> dict:
    """列出这个任务保存过的所有版本，用于撤销误操作。"""
    directory = _job_dir(job_id)
    main_tex = directory / "main.tex"
    current = main_tex.read_text(encoding="utf-8") if main_tex.is_file() else ""
    current_sha = _sha256_text(current) if current else None
    history = directory / "history"
    entries = []
    if history.is_dir():
        paths = sorted(history.glob("*.tex"), key=lambda path: path.stat().st_mtime, reverse=True)[:50]
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
                stat = path.stat()
            except OSError:
                continue
            first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
            entries.append(
                {
                    "name": path.name,
                    "saved_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "bytes": stat.st_size,
                    "lines": text.count("\n") + 1,
                    "sha256": _sha256_text(text),
                    "is_current": _sha256_text(text) == current_sha,
                    "first_line": first_line[:80],
                }
            )
    return {"job_id": job_id, "current_sha256": current_sha, "history": entries}


@app.post("/api/jobs/{job_id}/restore-history")
def restore_history(job_id: str, request: RestoreHistoryRequest) -> dict:
    """恢复到某个历史版本。当前版本本身也在历史里，所以可以再恢复回去。"""
    directory = _job_dir(job_id)
    name = request.name.strip()
    if not _HISTORY_NAME_PATTERN.fullmatch(name):
        raise HTTPException(status_code=400, detail="历史版本名不合法")
    path = directory / "history" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="历史版本不存在")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise HTTPException(status_code=409, detail="这个历史版本是空的，不能恢复")
    with _job_write_lock(job_id):
        _write_main_tex(directory, text)
        (directory / "suggestion.json").unlink(missing_ok=True)
        try:
            result = compile_tex(directory / "main.tex")
        except Exception as error:
            logger.exception("restore-history compilation failed")
            raise HTTPException(status_code=500, detail=f"{type(error).__name__}: 恢复历史版本后编译失败") from error
        public_result = _public_compile(result, job_id)
        _store_compile(directory, public_result)
        return {"compile": public_result, "tex": text, "restored": name}


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
    # baseline_sha256 校验和写入必须在同一把锁里：否则两个请求都能通过
    # "源码没变"的检查，然后各自写一版，后写的顶掉先写的。
    with _job_write_lock(job_id):
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
