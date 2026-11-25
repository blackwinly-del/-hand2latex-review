import os
import re
import shutil
import subprocess
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TECTONIC_DIR = _PROJECT_ROOT / "tools" / "tectonic"


def _find_tectonic() -> Path | None:
    """定位 tectonic 可执行文件。

    查找顺序：项目内置（Windows 为 tectonic.exe，其他平台无扩展名；两个名字
    都会兼容探测，避免从别的平台拷贝过来的目录用不了）→ 系统 PATH。
    都找不到返回 None，由 compile_tex 给出明确的安装提示。
    """
    preferred = "tectonic.exe" if os.name == "nt" else "tectonic"
    fallback = "tectonic" if os.name == "nt" else "tectonic.exe"
    for name in (preferred, fallback):
        candidate = _TECTONIC_DIR / name
        if candidate.is_file():
            return candidate
    found = shutil.which("tectonic")
    if found:
        return Path(found)
    return None


def parse_compile_errors(log: str) -> list[dict]:
    errors = []
    for match in re.finditer(r"(?m)^(?!warning:)(?:error:\s*)?([^\n]*?\.tex):(\d+):\s*(.*)$", log):
        errors.append({"line": int(match.group(2)), "message": match.group(3)})
    if errors:
        return errors

    match = re.search(r"(?m)^error:\s*(?:at\s+)?line\s+(\d+)(?::\s*)?(.*)$", log)
    if match:
        return [{"line": int(match.group(1)), "message": match.group(2)}]
    match = re.search(r"(?m)^error:\s*(.*)$", log)
    if match:
        return [{"line": None, "message": match.group(1)}]
    return []


def compile_tex(tex_path: str | Path, *, timeout: int = 120) -> dict:
    tex_path = Path(tex_path).resolve()
    if not tex_path.is_file():
        raise ValueError("tex file does not exist")

    pdf_path = tex_path.with_suffix(".pdf")
    try:
        pdf_path.unlink(missing_ok=True)
        tectonic = _find_tectonic()
        if tectonic is None:
            raise RuntimeError(
                "tectonic is not installed: expected tools/tectonic/"
                f"{'tectonic.exe' if os.name == 'nt' else 'tectonic'} in the project, "
                "or tectonic on PATH"
            )
        completed = subprocess.run(
            [str(tectonic), str(tex_path)],
            cwd=tex_path.parent,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"tectonic could not compile the document: {error}") from error

    log = (completed.stdout or "") + (completed.stderr or "")
    success = completed.returncode == 0 and pdf_path.is_file()
    return {
        "success": success,
        "pdf_path": str(pdf_path) if success else None,
        "log": log,
        "errors": parse_compile_errors(log),
        "returncode": completed.returncode,
    }
