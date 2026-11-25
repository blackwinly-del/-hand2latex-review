"""整页转录准确率评估。

放在 workbench/ 而不是 reasoning/：reasoning/ 属于内核（见 AGENTS.md），
内核同事正在改，这边不碰。评估逻辑本身不依赖内核任何实现，只比较文本。

此前整页这条线只有结构性验收（页数、页序、编译通过、PDF 页数），
`data/multipage_samples.json` 里明确写着 ``transcription_accuracy:
not_evaluated_without_full_page_truth``。也就是说"整页识别到底抄对没抄对"
这个问题一直没有数字。这个模块就是补这个缺口的。

设计上有一条硬约束：**真值没被人工确认过，就不许算准确率。**

为什么这条必须写进代码而不是写在文档里：手写整页转录的错误往往是成体系的
（比如把 ∈ 读成 €、把 \\frac 的分子分母对调），同一个模型读图写出的草稿
会和它自己的转录犯**同样的错**。拿这种草稿当真值去评，两边一起错，
准确率会显示 100%，而实际是错的。这比没有指标更危险——它给出的是
一个看起来很好的假数字。

用法：
    python -m workbench.full_page_eval                      # 只看门禁状态
    python -m workbench.full_page_eval --output x.json      # 生成报告
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MANIFEST = _ROOT / "data" / "pdf_pages_ground_truth.json"

# 只有这个状态才允许算准确率。其余（含缺字段）一律按"未确认"处理。
_CONFIRMED_STATES = {"user_confirmed", "ground_truth_user_confirmed"}


class GroundTruthNotConfirmed(RuntimeError):
    """真值还没被人工确认，不能用来算准确率。"""


def load_ground_truth(path: str | Path = _DEFAULT_MANIFEST) -> dict:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"整页真值文件不存在：{manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("真值文件里 pages 必须是非空列表")
    for page in pages:
        if not isinstance(page, dict):
            raise TypeError("pages 里每条必须是 dict")
        for key in ("page_id", "image_path"):
            value = page.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"真值条目缺少 {key}")
        lines = page.get("lines")
        if lines is not None and not isinstance(lines, list):
            raise TypeError(f"{page.get('page_id')} 的 lines 必须是列表")
    return data


def confirmation_state(manifest: dict) -> dict:
    """汇总门禁状态：谁确认了、谁还没确认、哪些还有不确定项。"""
    overall = manifest.get("review_status")
    confirmed = overall in _CONFIRMED_STATES
    pending = []
    disputed = []
    for page in manifest.get("pages", []):
        page_id = page.get("page_id")
        if page.get("human_review") != "confirmed":
            pending.append(page_id)
        if page.get("uncertainty"):
            disputed.append(page_id)
    return {
        "review_status": overall,
        "confirmed": confirmed,
        "pending_pages": pending,
        "pages_with_uncertainty": disputed,
        "total_pages": len(manifest.get("pages", [])),
    }


def _normalize_line(text: str) -> str:
    """行级比较前的归一：去掉首尾空白和行内多余空格。

    只做这一层归一，不做"数学等价"判断（比如不把 \\frac{1}{2} 和 0.5 当成一样）。
    整页评估要回答的是"转录对不对"，放宽到语义等价会把真实错误也放过。
    """
    return " ".join((text or "").split())


def compare_page(expected_lines: list[str], actual_text: str) -> dict:
    """逐行对比一页的转录结果。

    用行级最长公共子序列对齐，而不是"第 n 行对第 n 行"：整页识别多吐一行
    或少吐一行是常见的，按位置硬比会让后面所有行全部错位，得到的差异没法看。
    """
    expected = [_normalize_line(line) for line in expected_lines if _normalize_line(line)]
    actual = [_normalize_line(line) for line in (actual_text or "").splitlines() if _normalize_line(line)]

    # LCS 动态规划，页面行数在几十行量级，O(n*m) 完全够用。
    n, m = len(expected), len(actual)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if expected[i] == actual[j]:
                table[i][j] = table[i + 1][j + 1] + 1
            else:
                table[i][j] = max(table[i + 1][j], table[i][j + 1])

    matched = 0
    missing = []
    extra = []
    i = j = 0
    while i < n and j < m:
        if expected[i] == actual[j]:
            matched += 1
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            missing.append({"expected_line": i + 1, "text": expected[i]})
            i += 1
        else:
            extra.append({"actual_line": j + 1, "text": actual[j]})
            j += 1
    while i < n:
        missing.append({"expected_line": i + 1, "text": expected[i]})
        i += 1
    while j < m:
        extra.append({"actual_line": j + 1, "text": actual[j]})
        j += 1

    return {
        "expected_lines": n,
        "actual_lines": m,
        "matched_lines": matched,
        "missing": missing,
        "extra": extra,
        "exact_page_match": matched == n == m,
        "line_accuracy": round(matched / n, 4) if n else (1.0 if m == 0 else 0.0),
    }


def evaluate_full_pages(
    manifest: dict,
    transcriptions: dict[str, str],
    *,
    allow_unconfirmed: bool = False,
) -> dict:
    """对整页转录结果算准确率。

    transcriptions: page_id -> 识别出的整页文本（纯文本，不是 tex）。
    allow_unconfirmed: 仅供调试用。置 True 时报告里会显式标注结果不可引用。
    """
    state = confirmation_state(manifest)
    if not state["confirmed"] and not allow_unconfirmed:
        raise GroundTruthNotConfirmed(
            "整页真值还没被人工确认（review_status=%r，未确认页：%s）。"
            "现在算准确率得到的是「模型自评」的假数字：草稿和转录会犯同样的错，"
            "两边一起错时准确率显示 100%%。请对着原图逐行核对 "
            "data/pdf_pages_ground_truth.json，把 review_status 改成 "
            "user_confirmed 后再评估。" % (state["review_status"], state["pending_pages"])
        )

    pages = []
    for page in manifest.get("pages", []):
        page_id = page["page_id"]
        expected = page.get("lines") or []
        if page_id not in transcriptions:
            pages.append({
                "page_id": page_id,
                "evaluated": False,
                "reason": "没有提供这一页的转录结果",
            })
            continue
        result = compare_page(expected, transcriptions[page_id])
        result["page_id"] = page_id
        result["evaluated"] = True
        result["expected_blank"] = bool(page.get("expected_blank"))
        # 空白页要单独判：识别模型在空白页上"编出内容"是非常典型的失败，
        # 用行准确率看不出来（0 行预期、却吐了 5 行，会被算成 0%），
        # 这里明确标成 invented_content。
        if page.get("expected_blank"):
            result["invented_content"] = result["actual_lines"] > 0
        pages.append(result)

    evaluated = [page for page in pages if page.get("evaluated")]
    total_expected = sum(page["expected_lines"] for page in evaluated)
    total_matched = sum(page["matched_lines"] for page in evaluated)
    report = {
        "ground_truth_status": state,
        "pages": pages,
        "evaluated_pages": len(evaluated),
        "total_expected_lines": total_expected,
        "total_matched_lines": total_matched,
        "overall_line_accuracy": (
            round(total_matched / total_expected, 4) if total_expected else None
        ),
        "exact_page_matches": sum(1 for page in evaluated if page["exact_page_match"]),
        "invented_content_pages": [
            page["page_id"] for page in evaluated if page.get("invented_content")
        ],
    }
    if not state["confirmed"]:
        report["WARNING"] = (
            "真值未经人工确认，本报告的数字不可对外引用。"
            "它只说明草稿和转录有多一致，不说明转录有多准。"
        )
    return report


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="整页转录准确率评估")
    parser.add_argument("--manifest", default=str(_DEFAULT_MANIFEST), help="整页真值文件路径")
    parser.add_argument("--output", default=None, help="把门禁状态写到这个 json")
    args = parser.parse_args(argv)

    manifest = load_ground_truth(args.manifest)
    state = confirmation_state(manifest)
    print(f"真值状态：{state['review_status']}")
    print(f"总页数：{state['total_pages']}")
    print(f"已确认：{'是' if state['confirmed'] else '否'}")
    if state["pending_pages"]:
        print(f"待人工核对的页：{', '.join(state['pending_pages'])}")
    if state["pages_with_uncertainty"]:
        print(f"仍标注了不确定项的页：{', '.join(state['pages_with_uncertainty'])}")
    if not state["confirmed"]:
        print()
        print("准确率暂不计算。原因：草稿是模型读图写的，拿它当真值等于用 AI 的")
        print("转录评估 AI 的转录——两边犯同样的错时准确率会显示 100%。")
        print("请对着原图逐行核对后，把 review_status 改成 user_confirmed。")
    if args.output:
        Path(args.output).write_text(
            json.dumps({"ground_truth_status": state}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已写入 {args.output}")
    return 0 if state["confirmed"] else 2


if __name__ == "__main__":
    sys.exit(_cli())
