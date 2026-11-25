"""给 h2l-work 项目做一份带日期的完整源码备份包。

不是交付给用户的安装包（那是 scripts/package.ps1 的职责），而是"这台机器的
磁盘万一出事还能还原"的保险：包含 runtime/ 与 tools/，解压即可重新出安装包。
只排除纯缓存目录（__pycache__/.cache/node_modules/.venv），那些可重建。
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

PROJECT = Path(r"C:\Users\袁昊然\h2l-work")
OUT_DIR = Path(r"C:\Users\袁昊然\h2l-backups")
STAMP = "2026-11-25"
TOP = f"h2l-work-{STAMP}"

EXCLUDE_DIRS = {"__pycache__", ".cache", "node_modules", ".venv", ".venv-check", ".pytest_cache", ".ruff_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def main() -> int:
    if not PROJECT.is_dir():
        print(f"项目目录不存在：{PROJECT}", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUT_DIR / f"{TOP}.zip"
    if zip_path.exists():
        zip_path.unlink()

    count = 0
    total = 0
    skipped: list[str] = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        info = zipfile.ZipInfo(TOP + "/")
        info.external_attr = (0o40755 << 16) | 0x10
        archive.writestr(info, b"")

        for root, dirs, files in os.walk(PROJECT):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
            rel_root = Path(root).relative_to(PROJECT)
            for name in sorted(files):
                full = Path(root) / name
                if full.suffix.lower() in EXCLUDE_SUFFIXES:
                    continue
                arcname = (Path(TOP) / rel_root / name).as_posix()
                try:
                    size = full.stat().st_size
                    archive.write(full, arcname)
                except OSError as error:
                    skipped.append(f"{full} ({error})")
                    continue
                count += 1
                total += size

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"备份完成：{zip_path}")
    print(f"  文件数 {count}，原始 {total / (1024 * 1024):.1f} MB，压缩后 {size_mb:.1f} MB")
    if skipped:
        print(f"  跳过 {len(skipped)} 个读不了的文件：")
        for line in skipped[:10]:
            print("   -", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
