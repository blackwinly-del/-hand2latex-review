"""把暂存目录打成 zip，保证中文文件名在任何解压工具里都不乱码。

为什么不用 PowerShell 的 Compress-Archive：
它在 Windows PowerShell 5.1 下用系统 ANSI 代码页（中文机器上是 GBK）写文件名，
**却不设置 zip 的 UTF-8 标志位**（通用标志 bit 11）。于是：
  - 用 CP437 解码的工具（7-Zip、Windows 资源管理器、macOS 归档实用工具）看到乱码
  - `启动工作台.bat` 变成 `Õà¦Úù¡ÕÀÑõ¢£ÕŦ.bat`
用户根本认不出哪个是启动脚本。

Python 的 zipfile 在文件名含非 ASCII 字符时，会写 UTF-8 字节并置上 bit 11，
这是 zip 规范推荐的做法，所有现代工具都能正确还原。

用法：
    python scripts/make_zip.py <源目录> <输出.zip>

退出码：0 成功；非 0 失败（并打印原因）。
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path


def make_zip(source_dir: Path, zip_path: Path, compress_level: int = 9) -> tuple[int, int]:
    """把 source_dir 整个（含它自己的目录名）压进 zip_path。

    返回 (文件数, 总字节数)。
    """
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"源目录不存在：{source_dir}")
    if not source_dir.name:
        raise SystemExit(f"源目录没有名字，无法作为 zip 的顶层文件夹：{source_dir}")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    parent = source_dir.parent
    count = 0
    total = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=compress_level) as archive:
        # 顶层目录自身也要写一条，这样"解压到当前文件夹"会得到一个文件夹而不是散落一堆文件。
        info = zipfile.ZipInfo(source_dir.name + "/")
        info.external_attr = (0o40755 << 16) | 0x10  # 目录 + MS-DOS 目录位
        archive.writestr(info, b"")

        for root, dirs, files in os.walk(source_dir):
            dirs.sort()
            for name in sorted(files):
                full = Path(root) / name
                # 相对 parent 的路径 = 保留顶层目录名
                arcname = full.relative_to(parent).as_posix()
                try:
                    archive.write(full, arcname)
                    count += 1
                    total += full.stat().st_size
                except OSError as error:
                    raise SystemExit(f"读取失败：{full}（{error}）") from error
    return count, total


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("用法：python scripts/make_zip.py <源目录> <输出.zip>", file=sys.stderr)
        return 2
    source_dir = Path(argv[1])
    zip_path = Path(argv[2])
    count, total = make_zip(source_dir, zip_path)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"已打包 {count} 个文件（原始 {total / (1024 * 1024):.1f} MB）→ {zip_path}（{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
