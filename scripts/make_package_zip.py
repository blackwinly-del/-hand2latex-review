"""把打包暂存目录压成 zip，并当场核对中文文件名。

为什么不用 PowerShell 5.1 的 Compress-Archive：它走 .NET Framework，写出来的条目名
用反斜杠分隔（zip 规范要求正斜杠），第三方解压工具容易因此把名字处理坏，
用户看到的是乱码文件名，连"哪个是启动脚本"都认不出来。

用法：python scripts/make_package_zip.py <暂存目录> <输出 zip>
退出码 0 = 成功且核对通过；非 0 = 失败（原因打印成 JSON，避免中文在控制台变乱码）。
"""

import json
import sys
import zipfile
from pathlib import Path

# 这几个文件是用户拿到包第一眼要找的，名字错了就等于包不能用。
# 英文名那三个是给"解压工具不认 UTF-8 文件名标志"的情况兜底的，必须一起存在。
REQUIRED_NAMES = (
    "启动工作台.bat",
    "关闭工作台.bat",
    "安装说明.txt",
    "start.bat",
    "stop.bat",
    "INSTALL.txt",
)


def build_zip(staging: Path, out: Path) -> int:
    top = staging.name
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            # as_posix() 保证分隔符是 /，zf.write 会给非 ASCII 名字打上 UTF-8 标志位。
            archive.write(path, f"{top}/{path.relative_to(staging).as_posix()}")
            count += 1
    return count


def audit_names(top: str, entries: list) -> dict:
    """核对条目名。entries 是 (filename, flag_bits) 列表，拆出来是为了能直接喂假数据测试。"""
    names = {name for name, _ in entries}
    expected = {f"{top}/{name}" for name in REQUIRED_NAMES}
    non_ascii = [(name, bool(flag & 0x800)) for name, flag in entries if not name.isascii()]
    problems = []
    backslash = [name for name in names if "\\" in name]
    if backslash:
        problems.append(f"{len(backslash)} 个条目名含反斜杠（zip 规范要求正斜杠），例如 {backslash[0]}")
    missing = sorted(expected - names)
    if missing:
        problems.append("缺少必须的入口文件：" + "、".join(missing))
    without_flag = [name for name, flagged in non_ascii if not flagged]
    if without_flag:
        problems.append(f"{len(without_flag)} 个非 ASCII 条目没有 UTF-8 标志位，例如 {without_flag[0]}")
    return {
        "entries": len(names),
        "non_ascii_entries": len(non_ascii),
        "non_ascii_all_flagged_utf8": not without_flag,
        "required_names_present": not missing,
        "no_backslash_separators": not backslash,
        "problems": problems,
    }


def audit_zip(out: Path, top: str) -> dict:
    with zipfile.ZipFile(out) as archive:
        entries = [(info.filename, info.flag_bits) for info in archive.infolist()]
    return audit_names(top, entries)


def main() -> int:
    if len(sys.argv) != 3:
        print(json.dumps({"ok": False, "problems": ["用法：make_package_zip.py <暂存目录> <输出 zip>"]}))
        return 2
    staging = Path(sys.argv[1])
    out = Path(sys.argv[2])
    if not staging.is_dir():
        print(json.dumps({"ok": False, "problems": [f"暂存目录不存在：{staging}"]}))
        return 2
    count = build_zip(staging, out)
    report = audit_zip(out, staging.name)
    report["ok"] = not report["problems"]
    report["files_written"] = count
    report["zip_bytes"] = out.stat().st_size
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
