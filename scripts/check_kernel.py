"""核对内核文件有没有被动过。

用法（仓库根目录）：

    python scripts/check_kernel.py

为什么不能直接 ``sha256sum``：Windows 上 Git 默认 ``core.autocrlf=true``，
同一个提交 checkout 出来可能是 CRLF 也可能是 LF，直接算哈希会对不上，
看着像"代码被改了"，其实一个字没动。这里先统一行尾再算，结论才可信。

退出码：0 全部一致；1 有文件对不上（会打印差异说明）。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# 基线：内核文件的"归一化指纹"（行尾统一为 LF 之后再算 SHA256）。
# 这份基线对应仓库里不太久之前的状态；如果某个文件对不上，通常意味着
# 内核同事又往前推了一版——那不一定是你做错了什么，但**不要**顺手把它改回去。
BASELINE: dict[str, str] = {
    "recognizer.py": "f7764c9a8997a5e2a1b5709c3cbec3be4b168203d7d2d0b443044a01c3733623",
    "reasoner.py": "47580f7e58fb1c7637993b9118e34bc8b3be55daf589a9b373ca6481d2846ea2",
    "schemas.py": "cd3763eae4a5592c6d82017c4988eb8efec668ad2d1005a38aae0b2a04f1203b",
    "reasoning/validators.py": "97a4371d5db05c3c5286d7963dc5f8bd01cfb8f0c7a23facc47a5af9f9f70e1e",
    "reasoning/context.py": "45273eb4fb9d3f65719b393edb0e518e94d44c30622b248109bbfc2a66e0a60d",
    "reasoning/render_check.py": "8e4b4c9556e54c9d238371b5b37fd2a8dda099346c25b1d33f9eb45f63938a80",
    "workbench/full_page.py": "737388000673c64255940e1f8bdddfa500448bd701f6e083a1cd3d5f9576a124",
    "workbench/fix.py": "5446713d169b0ba89f815bc210377d0d82958dc5c3aa854dd80f6f7fec494c2d",
}

ROOT = Path(__file__).resolve().parent.parent


def _normalized_digest(path: Path) -> str:
    """按 LF 归一化后算 SHA256，结果与 checkout 时的行尾设置无关。"""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    changed: list[str] = []
    missing: list[str] = []

    for rel, expected in BASELINE.items():
        path = ROOT / rel
        if not path.is_file():
            missing.append(rel)
            print(f"  缺失  {rel}")
            continue

        actual = _normalized_digest(path)
        if actual == expected:
            print(f"  一致  {rel}")
        else:
            changed.append(rel)
            print(f"  改动  {rel}")
            print(f"        期望 {expected}")
            print(f"        实际 {actual}")

    print()
    if missing:
        print(f"有 {len(missing)} 个内核文件找不到——目录结构可能变了，先确认自己在仓库根目录。")
        return 1

    if not changed:
        print("内核没有变化，你可以放心只改前端。")
        return 0

    print(f"有 {len(changed)} 个内核文件与基线不同：{', '.join(changed)}")
    print()
    print("这不一定是错误，可能是内核同事正常推进了一版。但你需要确认：")
    print("  1. 这些改动是你做的吗？不是 -> 大概率是同事推上来的，正常。")
    print("  2. 是你做的吗？那你越界了，先跟对方说明再继续。")
    print("  3. 无论哪种，都不要为了让脚本变绿而把文件改回基线。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
