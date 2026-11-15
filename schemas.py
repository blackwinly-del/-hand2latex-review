"""schemas.py —— A / B / C 三人的共享数据契约。

对齐 `CONTRACT.md` v0.2（C 模块公共契约讨论稿）。任何字段、任何名字的改动
都必须三人一起同意，平时不要动这个文件。

三个结构：
  Candidate    : B 的输出单位，5 个字段（A 展示、C 消费）
  Change       : C 的修改记录（按 rule 区分字段）
  RefineResult : C 的 refine() 返回整体（A 展示）

⚠️ v0.1 → v0.2 的不兼容变更（已按契约执行）：
  - Candidate 从 3 字段扩到 5 字段：新增 latency_ms、error。
  - 失败不再用 "[ERROR] ..." 前缀塞进 latex；改为 latex="" + error="原因"。
    旧的 ERROR_PREFIX 常量已删除，is_error() 现在只看 error 字段。
  - Change 从 {from,to,reason} 改为按 rule 区分的 {rule,before,after,...}。
  - RefineResult 新增 risk_score（MLP 未接入，当前恒为 None）。
  - B 不再 strip 输出，首尾空白由 C 清理并记 trim_outer_whitespace。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# Candidate 的字段名与顺序都是契约，禁止增删。
CANDIDATE_KEYS = ("engine", "latex", "score", "latency_ms", "error")

# C 允许返回的置信度取值（规则等级，不是概率）
CONFIDENCE_LEVELS = ("high", "medium", "low")

# changes 里允许的 rule
CHANGE_RULE_CONTEXT = "context_candidate_selection"
CHANGE_RULE_TRIM = "trim_outer_whitespace"
CHANGE_RULE_LOCAL = "local_span_replacement"  # 提案，尚未实现


# ---------------------------------------------------------------------------
# 结构定义
# ---------------------------------------------------------------------------


class Candidate(TypedDict):
    """B 的 recognize() 返回列表中的一项。"""

    engine: str              # 引擎标识，C 用它判断跨引擎一致性
    latex: str               # 忠实转录的 LaTeX；失败时为空字符串
    score: Optional[float]   # 识别器真实分数；没有真实分数必须是 None
    latency_ms: float        # 识别延迟，C 不用于候选选择
    error: Optional[str]     # 失败原因；非 None 时 C 必须跳过该候选


Change = TypedDict(
    "Change",
    {
        "rule": str,
        "before": str,
        "after": str,
        "selected_index": int,
        "reason": str,
    },
    total=False,
)


class RefineResult(TypedDict):
    """C 的 refine() 返回值。"""

    raw_latex: str
    final_latex: str
    confidence: str        # high / medium / low
    changes: List[Change]
    need_review: bool      # True 表示必须人工复核
    risk_score: Optional[float]  # MLP 未接入，恒为 None


# ---------------------------------------------------------------------------
# 构造工具（B / C 共用，避免各写一份格式跑偏）
# ---------------------------------------------------------------------------


def make_candidate(
    engine: str,
    latex: str,
    score: Optional[float] = None,
    latency_ms: float = 0.0,
    error: Optional[str] = None,
) -> Candidate:
    """构造一个合法候选。score 没有真实值就传 None，禁止编造。"""
    return {
        "engine": engine,
        "latex": latex,
        "score": score,
        "latency_ms": latency_ms,
        "error": error,
    }


def make_error(engine: str, message: str, latency_ms: float = 0.0) -> Candidate:
    """构造一个失败候选：latex 为空，原因放 error。C 会跳过它并给出 need_review。"""
    return make_candidate(engine, "", None, latency_ms, message)


def is_error(candidate: Dict[str, Any]) -> bool:
    """是否需要跳过该候选。判定依据是 error 字段，不再看 latex 前缀。"""
    return candidate.get("error") is not None


def error_message(candidate: Dict[str, Any]) -> str:
    """取出失败候选里的可读原因（给 A 展示用）。"""
    error = candidate.get("error")
    return error if isinstance(error, str) else ""


def is_candidate(obj: Any) -> bool:
    """校验一个对象是否是合法 Candidate（A / C 拿到 B 的结果时可以断言一下）。"""
    return (
        isinstance(obj, dict)
        and set(obj.keys()) == set(CANDIDATE_KEYS)
        and isinstance(obj.get("engine"), str)
        and isinstance(obj.get("latex"), str)
        and (obj.get("score") is None or isinstance(obj.get("score"), (int, float)))
        and isinstance(obj.get("latency_ms"), (int, float))
        and (obj.get("error") is None or isinstance(obj.get("error"), str))
    )


def independent_engines(candidates: List[Dict[str, Any]]) -> List[str]:
    """返回候选里出现过的不同引擎名（去重、保持出现顺序）。

    C 判断"多个不同引擎支持同一结果 → high"时必须用它：同一个 engine 的多条候选
    只是同一个模型跑了几次（比如多视角），错误高度相关，不能当独立证据投票。
    """
    seen: List[str] = []
    for item in candidates:
        engine = item.get("engine")
        if isinstance(engine, str) and engine not in seen:
            seen.append(engine)
    return seen


# ---------------------------------------------------------------------------
# changes 记录（契约 §4）
# ---------------------------------------------------------------------------


def make_change_context(
    before: str, after: str, selected_index: int, reason: str
) -> Change:
    """上下文改选了非首个去重候选。选择首个候选时不记录。"""
    return {
        "rule": CHANGE_RULE_CONTEXT,
        "before": before,
        "after": after,
        "selected_index": selected_index,
        "reason": reason,
    }


def make_change_trim(before: str, after: str) -> Change:
    """首尾空白清理，仅在确实发生变化时记录。"""
    return {"rule": CHANGE_RULE_TRIM, "before": before, "after": after}


def is_change(obj: Any) -> bool:
    """粗校验一条修改记录：必须有 rule，且 before/after 都是字符串。"""
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("rule"), str)
        and isinstance(obj.get("before"), str)
        and isinstance(obj.get("after"), str)
    )
