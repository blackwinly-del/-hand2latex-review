"""核对内核文件有没有被动过。

用法（仓库根目录）：

    python scripts/check_kernel.py

为什么不能直接 ``sha256sum``：Windows 上 Git 默认 ``core.autocrlf=true``，
同一个提交 checkout 出来可能是 CRLF 也可能是 LF，直接算哈希会对不上，
看着像"代码被改了"，其实一个字没动。这里先统一行尾再算，结论才可信。

基线怎么来的（2026-11-25 修）：
    旧的写法是把 8 个哈希手抄进 ``BASELINE``，结果抄错了两个
    （``recognizer.py`` 与 ``workbench/full_page.py`` 抄的是 hand2latex-review
    分支上的旧内核，而入库的是 11-25 备份里的新内核）。于是从建库那一刻起
    这两个文件就一直飘红——不是内核被改，是基线录错了。

    现在优先用 ``KERNEL_BASELINE_COMMIT`` 这个提交里**真实存在的文件内容**来算
    基线，手抄的哈希只作为没有 git 时的兜底。这样只要基线提交本身没被改写，
    基线就不会错，也不再有"抄错"这种可能。

    要推进基线（内核同事真的改了一版），改 ``KERNEL_BASELINE_COMMIT`` 一处即可，
    不要逐个去抄哈希。

退出码：0 全部一致；1 有文件对不上（会打印差异说明）。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

# 基线提交：内核文件的基准状态取这个提交里的内容。
# 2026-11-25 建库提交，内容来自当日 17:17 的完整备份。
KERNEL_BASELINE_COMMIT = "992dd4e"

# 兜底基线：仓库里没有 git（比如对方拿到的是解压后的交付包）时用这份。
# 值与 KERNEL_BASELINE_COMMIT 中的内容一致，改基线时两处要一起改。
BASELINE: dict[str, str] = {
    "recognizer.py": "d4fab5ffb65e5642e179894f5c1d93979d93b84f68dd663b9ad34a91ae96d321",
    "reasoner.py": "47580f7e58fb1c7637993b9118e34bc8b3be55daf589a9b373ca6481d2846ea2",
    "schemas.py": "cd3763eae4a5592c6d82017c4988eb8efec668ad2d1005a38aae0b2a04f1203b",
    "reasoning/validators.py": "97a4371d5db05c3c5286d7963dc5f8bd01cfb8f0c7a23facc47a5af9f9f70e1e",
    "reasoning/context.py": "45273eb4fb9d3f65719b393edb0e518e94d44c30622b248109bbfc2a66e0a60d",
    "reasoning/render_check.py": "8e4b4c9556e54c9d238371b5b37fd2a8dda099346c25b1d33f9eb45f63938a80",
    "workbench/full_page.py": "8e4a4bdb8e77b129ff17603686fbc8d8da548cb5e109a5c5b056cfb712075d63",
    "workbench/fix.py": "5446713d169b0ba89f815bc210377d0d82958dc5c3aa854dd80f6f7fec494c2d",
}

ROOT = Path(__file__).resolve().parent.parent


def _normalize(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _normalized_digest(path: Path) -> str:
    """按 LF 归一化后算 SHA256，结果与 checkout 时的行尾设置无关。"""
    return hashlib.sha256(_normalize(path.read_bytes())).hexdigest()


def _git_baseline() -> dict[str, str] | None:
    """从基线提交里取内核文件内容算指纹。

    取不到（没有 git、不是仓库、基线提交已不存在）时返回 None，由调用方退回兜底值。
    """
    digests: dict[str, str] = {}
    for rel in BASELINE:
        try:
            done = subprocess.run(
                ["git", "show", f"{KERNEL_BASELINE_COMMIT}:{rel}"],
                cwd=ROOT,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0 or not done.stdout:
            return None
        digests[rel] = hashlib.sha256(_normalize(done.stdout)).hexdigest()
    return digests


def main() -> int:
    baseline = _git_baseline()
    if baseline is not None:
        source = f"git 提交 {KERNEL_BASELINE_COMMIT}"
    else:
        baseline = BASELINE
        source = "脚本内置值（没有可用的 git 提交）"
    print(f"基线来源：{source}\n")

    changed: list[str] = []
    missing: list[str] = []

    for rel, expected in baseline.items():
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
    print(f"  4. 确认要推进基线时，改 KERNEL_BASELINE_COMMIT（当前 {KERNEL_BASELINE_COMMIT}）"
          " 与内置兜底值，不要只改一处。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
