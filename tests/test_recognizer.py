"""test_recognizer.py —— B 的自测脚本，不需要 A / C，也不需要真的装好 paddle。

对齐 CONTRACT.md v0.2：候选 5 个字段、失败走 error 字段、B 不做 strip、
去重只按 strip 后比较。

用法（在仓库根目录执行）：
    python tests/test_recognizer.py            # 只测接口契约（mock 后端，秒出结果）
    python tests/test_recognizer.py --real     # 额外跑一次真模型（需要装好 paddleocr）

注意：这是独立自检脚本（自定义 runner，非 unittest.TestCase），
被 `python -m unittest discover -s tests` 导入时无副作用，
只有直接运行才会执行全部检查。

任何一条不通过都会以非 0 退出码结束，方便以后接 CI。
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __name__ == "__main__":
    # 直接运行时把仓库根目录加进 sys.path（unittest discover 时根目录本来就在）
    sys.path.insert(0, str(_PROJECT_ROOT))
if "--real" not in sys.argv:
    os.environ["RECOGNIZER_BACKEND"] = "mock"

import recognizer  # noqa: E402  （要在设置环境变量之后导入）
import schemas  # noqa: E402
from schemas import CANDIDATE_KEYS, make_candidate, make_error  # noqa: E402

SAMPLE = _PROJECT_ROOT / "samples" / "sample_plus.png"

_failures: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as exc:
        _failures.append(f"{name}: {exc}")
        print(f"FAIL {name}: {exc}")
    except Exception:  # noqa: BLE001
        _failures.append(f"{name}: 抛异常")
        print(f"FAIL {name}: 抛出未捕获异常")
        traceback.print_exc()
    else:
        print(f"PASS {name}")


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


def _fake_views(names: list[str], recorder: dict | None = None):
    """替换 _iter_views，伪造 N 个视角，不依赖 PIL。"""

    def _ctx(path: str, thorough: bool):
        if recorder is not None:
            recorder["thorough"] = thorough

        @contextmanager
        def _inner():
            yield [(f"{path}#{name}", name) for name in names]

        return _inner()

    return _ctx


@contextmanager
def patched(views_names: list[str] | None = None, run_engine=None):
    """临时替换视角生成 / 引擎执行，退出时还原。"""
    old_views, old_run = recognizer._iter_views, recognizer._run_engine
    if views_names is not None:
        recognizer._iter_views = _fake_views(views_names)
    if run_engine is not None:
        recognizer._run_engine = run_engine
    try:
        yield
    finally:
        recognizer._iter_views, recognizer._run_engine = old_views, old_run


# ---------------------------------------------------------------------------
# 契约测试（CONTRACT.md §2.2）
# ---------------------------------------------------------------------------


def test_returns_list_of_dict() -> None:
    result = recognizer.recognize(str(SAMPLE))
    assert isinstance(result, list), f"必须返回 list，实际 {type(result)}"
    assert len(result) >= 1, "至少要有一个候选"
    for item in result:
        assert isinstance(item, dict), f"候选必须是 dict，实际 {type(item)}"
        assert set(item.keys()) == set(CANDIDATE_KEYS), (
            f"字段必须恰好是 {CANDIDATE_KEYS}，实际 {list(item.keys())}"
        )
        assert isinstance(item["engine"], str) and item["engine"], "engine 必须是非空字符串"
        assert isinstance(item["latex"], str), "latex 必须是字符串"
        assert item["score"] is None or isinstance(item["score"], float), "score 必须是 None 或数字"
        assert isinstance(item["latency_ms"], (int, float)), "latency_ms 必须是数字"
        assert item["error"] is None or isinstance(item["error"], str), "error 必须是 None 或字符串"


def test_never_makes_up_score() -> None:
    for item in recognizer.recognize(str(SAMPLE)):
        assert item["score"] is None, "模型没给分数时必须是 None，不能编造置信度"


def test_latency_is_number() -> None:
    for item in recognizer.recognize(str(SAMPLE)):
        assert item["latency_ms"] >= 0, f"latency_ms 不能为负，实际 {item['latency_ms']}"


def test_error_semantics() -> None:
    """失败的判断依据是 error 字段，不是 latex 前缀。"""
    failed = make_error("pp_formulanet_l", "boom")
    assert failed["latex"] == "", "失败候选的 latex 必须为空字符串"
    assert failed["error"] == "boom"
    assert schemas.is_error(failed) is True
    assert schemas.is_error(make_candidate("pp_formulanet_l", "x")) is False


def test_old_three_field_candidate_rejected() -> None:
    """旧的三字段候选必须被判为不符合契约，防止回退。"""
    legacy = {"engine": "pp_formulanet_l", "latex": "x", "score": None}
    assert schemas.is_candidate(legacy) is False, "三字段旧格式不应再通过校验"


def test_change_shapes() -> None:
    """changes 记录按 rule 区分，字段名是 before/after 而不是 from/to。"""
    trim = schemas.make_change_trim(" x ", "x")
    assert trim["rule"] == "trim_outer_whitespace"
    assert set(trim) == {"rule", "before", "after"}
    ctx = schemas.make_change_context("x+1", "x-1", 1, "根据原图选择第二候选")
    assert ctx["rule"] == "context_candidate_selection"
    assert ctx["selected_index"] == 1
    assert set(ctx) == {"rule", "before", "after", "selected_index", "reason"}
    assert "from" not in ctx and "to" not in ctx, "不得再使用旧的 from/to 字段名"
    assert schemas.is_change(trim) and schemas.is_change(ctx)


def test_refine_result_has_risk_score() -> None:
    """契约 §3 的返回结构必须能表达 risk_score。"""
    hints = getattr(schemas.RefineResult, "__annotations__", {})
    assert "risk_score" in hints, "RefineResult 缺少 risk_score 字段"


def test_missing_file() -> None:
    result = recognizer.recognize(str(_PROJECT_ROOT / "samples" / "根本不存在.png"))
    assert len(result) == 1, "文件不存在也要返回 1 条失败候选"
    assert result[0]["latex"] == "", "失败候选的 latex 必须是空串，不能塞报错文本"
    assert result[0]["error"], "必须通过 error 字段说明原因"
    assert "不存在" in result[0]["error"], f"错误信息要说清原因，实际：{result[0]['error']}"


def test_directory_input() -> None:
    result = recognizer.recognize(str(_PROJECT_ROOT / "samples"))
    assert result[0]["latex"] == "" and result[0]["error"], "传目录应返回失败候选"
    assert "目录" in result[0]["error"], f"应提示给的是目录，实际：{result[0]['error']}"


def test_bad_suffix() -> None:
    weird = _PROJECT_ROOT / "samples" / "note.txt"
    weird.write_text("not an image", encoding="utf-8")
    try:
        result = recognizer.recognize(str(weird))
        assert result[0]["error"], "不支持的格式应通过 error 说明"
    finally:
        weird.unlink(missing_ok=True)


def test_gif_allowed() -> None:
    """.gif 必须和白名单一致（契约 §2.1 支持 gif）。"""
    assert ".gif" in recognizer._ALLOWED_SUFFIX, "白名单缺少 .gif"


def test_empty_path() -> None:
    for bad in ("", None):  # type: ignore[list-item]
        result = recognizer.recognize(bad)  # type: ignore[arg-type]
        assert isinstance(result, list) and result, f"{bad!r} 也要返回失败候选"
        assert result[0]["error"], f"{bad!r} 应通过 error 说明原因"


def test_official_result_shape() -> None:
    """官方返回结构解析；且 B 不得 strip（契约要求 C 来清理）。"""

    class FakeResult:
        def __init__(self, payload):
            self._payload = payload

        @property
        def json(self):
            return self._payload

    official = FakeResult(
        {"res": {"input_path": "x.png", "page_index": None, "rec_formula": r" \frac{x^{2}}{2} "}}
    )
    assert recognizer._extract_latex(official) == r" \frac{x^{2}}{2} ", "B 不得改动模型输出的首尾空白"
    assert recognizer._extract_score(official) is None, "官方结构里没有分数，必须取到 None"

    variant = FakeResult({"res": {"latex": "x+1"}})
    assert recognizer._extract_latex(variant) == "x+1"
    empty = FakeResult({"res": {}})
    assert recognizer._extract_latex(empty) == "", "取不到公式时返回空串"


def test_no_strip_end_to_end() -> None:
    """端到端：模型给的是带空白原文，交出去也得是带空白原文。"""

    def fake_run(engine, image_path):
        return [make_candidate(engine, "  x^2  ", None, 12.3)]

    with patched(views_names=["orig"], run_engine=fake_run):
        result = recognizer.recognize(str(SAMPLE), thorough=True)
    assert result[0]["latex"] == "  x^2  ", "B 提前 strip 会让 C 的 trim 记录永远不触发"


def test_no_exception_leaks() -> None:
    """B 的边界：任何输入都不许抛异常。"""
    for bad in (123, [], {"a": 1}, "  "):
        recognizer.recognize(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 多视角扩池（TAMER 那层的候选池）
# ---------------------------------------------------------------------------


def test_views_off_by_default() -> None:
    """默认（thorough=False）只跑原图，别偷偷变慢。"""
    recorder: dict = {}
    old = recognizer._iter_views
    recognizer._iter_views = _fake_views(["orig"], recorder)
    try:
        recognizer.recognize(str(SAMPLE))
    finally:
        recognizer._iter_views = old
    assert recorder["thorough"] is False, "默认不该开启多视角"


def test_dedupe_same_latex_across_views() -> None:
    """5 个视角吐出同一串 → 只能算 1 条候选（同模型重复不算独立证据）。"""

    def fake_run(engine, image_path):
        return [make_candidate(engine, r"\frac{x^{2}}{2}", None, 1.0)]

    with patched(["orig", "zoom1.5", "rot-2", "rot2", "binarize"], fake_run):
        result = recognizer.recognize(str(SAMPLE), thorough=True)
    assert len(result) == 1, f"重复候选必须去重成 1 条，实际 {len(result)} 条"


def test_dedupe_only_strips() -> None:
    """去重只按 strip 后比较：首尾空白算重复，内部空白差异不算。"""
    outputs = iter([" x^2 ", "x^2", "x ^ 2"])

    def fake_run(engine, image_path):
        return [make_candidate(engine, next(outputs), None, 1.0)]

    with patched(["orig", "zoom1.5", "rot-2"], fake_run):
        result = recognizer.recognize(str(SAMPLE), thorough=True)
    latexes = [c["latex"] for c in result]
    assert latexes == [" x^2 ", "x ^ 2"], (
        f"首尾空白差异应合并、内部空白差异应保留，实际 {latexes}"
    )


def test_distinct_candidates_survive() -> None:
    """不同视角吐出不同串时必须都保留，否则 C 无池可筛。"""

    def fake_run(engine, image_path):
        name = image_path.split("#")[-1]
        return [make_candidate(engine, f"x+{name}", None, 1.0)]

    with patched(["orig", "zoom1.5", "rot-2"], fake_run):
        result = recognizer.recognize(str(SAMPLE), thorough=True)
    assert len(result) == 3, f"三个不同的串应全部保留，实际 {len(result)} 条"
    assert result[0]["latex"] == "x+orig", "原图视角必须排第一（最可信、最先被保留）"


def test_partial_failure_does_not_pollute_pool() -> None:
    """个别视角失败时，失败候选不能混进候选池。"""

    def fake_run(engine, image_path):
        if "rot" in image_path:
            return [make_error(engine, "boom", 1.0)]
        return [make_candidate(engine, r"\frac{x^{2}}{2}", None, 1.0)]

    with patched(["orig", "rot-2", "rot2"], fake_run):
        result = recognizer.recognize(str(SAMPLE), thorough=True)
    assert len(result) == 1, f"只有 orig 成功，应得 1 条，实际 {len(result)} 条"
    assert all(c["error"] is None for c in result), "候选池里不该有失败候选"


def test_blank_results_are_skipped() -> None:
    """纯空白结果不进池子；全都空白时给一条失败候选。"""

    def fake_run(engine, image_path):
        return [make_candidate(engine, "   ", None, 1.0)]

    with patched(["orig", "zoom1.5"], fake_run):
        result = recognizer.recognize(str(SAMPLE), thorough=True)
    assert len(result) == 1 and result[0]["error"], "全空白应返回一条失败候选，交给 C 判 need_review"


def test_all_fail_returns_single_error() -> None:
    """所有视角都失败 → 一条汇总失败候选，A 才好展示。"""

    def fake_run(engine, image_path):
        return [make_error(engine, "模型挂了", 1.0)]

    with patched(["orig", "zoom1.5"], fake_run):
        result = recognizer.recognize(str(SAMPLE), thorough=True)
    assert len(result) == 1, "全失败时应合并成 1 条"
    assert result[0]["latex"] == "" and "模型挂了" in (result[0]["error"] or "")


def test_candidate_cap() -> None:
    """候选数必须封顶，否则 C 的多模态仲裁 token 会爆。"""
    names = [f"v{i}" for i in range(10)]
    counter = {"n": 0}

    def fake_run(engine, image_path):
        counter["n"] += 1
        return [make_candidate(engine, f"x+{counter['n']}", None, 1.0)]

    old_cap = os.environ.get("RECOGNIZER_MAX_CANDIDATES")
    os.environ["RECOGNIZER_MAX_CANDIDATES"] = "4"
    try:
        with patched(names, fake_run):
            result = recognizer.recognize(str(SAMPLE), thorough=True)
    finally:
        if old_cap is None:
            os.environ.pop("RECOGNIZER_MAX_CANDIDATES", None)
        else:
            os.environ["RECOGNIZER_MAX_CANDIDATES"] = old_cap
    assert len(result) == 4, f"上限 4，实际 {len(result)} 条"


def test_jsonl_log() -> None:
    """打开 RECOGNIZER_LOG_JSONL 后要能落一行合法 JSON，供 C 做测试集分析。"""
    log_path = _PROJECT_ROOT / "_tmp_recognize.jsonl"
    log_path.unlink(missing_ok=True)
    old = os.environ.get("RECOGNIZER_LOG_JSONL")
    os.environ["RECOGNIZER_LOG_JSONL"] = str(log_path)
    try:
        with patched(
            views_names=["orig"],
            run_engine=lambda engine, image_path: [
                make_candidate(engine, r"\frac{x^{2}}{2}+1", None, 0.0)
            ],
        ):
            recognizer.recognize(str(SAMPLE))
    finally:
        if old is None:
            os.environ.pop("RECOGNIZER_LOG_JSONL", None)
        else:
            os.environ["RECOGNIZER_LOG_JSONL"] = old
    try:
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1, f"应写 1 行，实际 {len(lines)} 行"
        record = json.loads(lines[0])
        assert record["image"].endswith("sample_plus.png")
        first = record["candidates"][0]
        assert {"engine", "latex", "latency_ms", "hits", "views"} <= set(first)
    finally:
        log_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 真模型冒烟（可选）
# ---------------------------------------------------------------------------


def test_real_model() -> None:
    if "--real" not in sys.argv:
        print("SKIP 真模型测试（加 --real 才跑）")
        return
    old = os.environ.get("RECOGNIZER_BACKEND")
    os.environ["RECOGNIZER_BACKEND"] = "paddle"
    try:
        result = recognizer.recognize(str(SAMPLE))
        print("   真模型输出：", json.dumps(result, ensure_ascii=False))
        assert isinstance(result, list) and result
        for item in result:
            assert set(item.keys()) == set(CANDIDATE_KEYS)
    finally:
        if old is None:
            os.environ.pop("RECOGNIZER_BACKEND", None)
        else:
            os.environ["RECOGNIZER_BACKEND"] = old


def main() -> int:
    if not SAMPLE.exists():
        print("缺少测试图片，请先运行：python samples/_gen_sample.py")
        return 1

    print(f"后端 = {os.environ.get('RECOGNIZER_BACKEND')}\n")
    check("候选 5 字段且类型正确", test_returns_list_of_dict)
    check("没分数时 score 必须是 None", test_never_makes_up_score)
    check("latency_ms 是数字", test_latency_is_number)
    check("失败走 error 字段、latex 为空", test_error_semantics)
    check("旧三字段候选被拒绝", test_old_three_field_candidate_rejected)
    check("changes 记录格式符合契约", test_change_shapes)
    check("RefineResult 含 risk_score", test_refine_result_has_risk_score)
    check("文件不存在 → 失败候选", test_missing_file)
    check("传目录 → 失败候选", test_directory_input)
    check("格式不支持 → 失败候选", test_bad_suffix)
    check(".gif 在白名单里", test_gif_allowed)
    check("空路径 / None → 失败候选", test_empty_path)
    check("解析官方 Result 结构且不 strip", test_official_result_shape)
    check("端到端不 strip", test_no_strip_end_to_end)
    check("任何输入都不抛异常", test_no_exception_leaks)
    check("默认不开启多视角（不变慢）", test_views_off_by_default)
    check("多视角同串 → 去重成 1 条", test_dedupe_same_latex_across_views)
    check("去重只 strip、不折叠内部空白", test_dedupe_only_strips)
    check("不同候选全部保留，原图优先", test_distinct_candidates_survive)
    check("个别视角失败不污染候选池", test_partial_failure_does_not_pollute_pool)
    check("全空白结果不进池", test_blank_results_are_skipped)
    check("全失败 → 合并成 1 条", test_all_fail_returns_single_error)
    check("候选数封顶", test_candidate_cap)
    check("JSONL 运行日志可落盘", test_jsonl_log)
    check("真模型冒烟", test_real_model)

    print()
    if _failures:
        print(f"共 {len(_failures)} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
