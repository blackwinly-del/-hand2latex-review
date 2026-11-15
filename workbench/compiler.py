import re
import subprocess
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TECTONIC = _PROJECT_ROOT / "tools" / "tectonic" / "tectonic.exe"


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
        if not _TECTONIC.is_file():
            raise RuntimeError("tectonic is not installed in tools/tectonic")
        completed = subprocess.run(
            [str(_TECTONIC), str(tex_path)],
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
