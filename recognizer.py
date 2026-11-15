"""recognizer.py —— 任务 B 的全部职责：图片 → LaTeX 候选列表。

对齐 `CONTRACT.md` v0.2。对外只有一个函数（契约，签名不许改）：

    recognize(image_path: str) -> list[dict]
    返回 [{
        "engine": "pp_formulanet_l",
        "latex": "\\frac{x^2}{2}",
        "score": None,
        "latency_ms": 1234.5,
        "error": None,
    }, ...]

六条铁律：
1. 永远返回 list[dict]。文件不存在、模型报错，也返回一个失败候选
   （latex=""、error="原因"），绝不向上抛异常把 A 的页面炸掉。
   ⚠️ 不再用 "[ERROR] ..." 前缀塞进 latex——那样 C 会把它当成合法公式，
   结构检查还查得过去，最后以 need_review=false 的"成功"结果返回给用户。
2. 不校验 LaTeX 语法，不判断树结构是否合法，不给候选打分排序——这些是 C 的事。
3. **B 不做 strip**：模型吐什么就交什么，首尾空白留给 C 清理并记
   trim_outer_whitespace（契约 §4.2）。B 若提前 strip，C 那条规则永远不触发。
4. 模型不给置信度就填 None，禁止编造 score。多视角命中次数不是分数，
   它只写进日志，绝不塞进接口（同一个模型跑 5 次不代表 5 份独立证据）。
5. 不 import A / C 的代码，不写页面，不调大模型。只依赖 schemas.py 这一个共享契约。
6. 全过程确定性：视角表固定、解码贪心、无随机数。同一张图跑两次结果必须一模一样，
   否则 C 用测试集做"有无 reasoner 的错误率对比"就是噪声。

【去重口径】（契约 §2.2：按清理后的完整字符串去重）
只做 strip 后比较，**不折叠内部空白**。` x ^ 2 ` 与 `x ^ 2` 算同一条；
`x ^ 2` 与 `x^2` 算两条——语义等价判断属于 C 的树结构分析，B 不做。

【为什么 B 要能给出多个候选（这是 TAMER 那一层的落点）】
TAMER（AAAI 2025）的做法是：训练时联合优化序列预测和树结构预测，推理时用树结构
评分去筛选输出。B 不换模型架构，所以拿不到"树结构评分"——那是 C 的活儿；但筛选
的前提是**有多个输出可筛**。PaddleOCR 的封装不暴露 n-best / beam search，所以 B
只能用两种不换模型的办法把候选池扩出来：
    a) 异构引擎：再加一个 UniMERNet（不同架构，错误才不相关，投票才有价值）
    b) 同模型多视角：原图 / 放大 / 轻微旋转 / 二值化，各跑一次
(b) 是启发式的，收益未经验证，默认关闭；它产出的候选高度相关，不能当独立证据用。
两种方式产出的候选都只带"基础引擎名"，C 用 engine 分组即可判断独立性。

环境变量：
    RECOGNIZER_MODEL          默认 "PP-FormulaNet-L"
                              可换 "PP-FormulaNet_plus-L" / "PP-FormulaNet_plus-M"（中文更强）
    RECOGNIZER_MODEL_DIR      可选模型目录；默认优先使用项目内 models/PP-FormulaNet-L
    RECOGNIZER_DEVICE         默认 "cpu"，有显卡填 "gpu:0"
    RECOGNIZER_BACKEND        默认 "paddle"；设成 "mock" 返回明确失败候选，
                              仅用于联调失败回退，不得当成真实识别结果
    RECOGNIZER_ENGINES        默认 "pp_formulanet_l"；加第二模型时改成
                              "pp_formulanet_l,unimernet"，A / C 一行都不用改
    RECOGNIZER_VIEWS          默认 "off"；设 "on" 默认就开多视角（慢 3~5 倍）
    RECOGNIZER_MAX_CANDIDATES 默认 6，去重后候选数上限，防止 C 的仲裁 token 爆炸
    RECOGNIZER_LOG_JSONL      设成文件路径则每次识别追加一行 JSON，供 C 做测试集分析

单独运行：
    python recognizer.py samples/sample_plus.png            # 单视角，快
    python recognizer.py samples/sample_plus.png --thorough # 多视角，扩候选池
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from schemas import (
    Candidate,
    error_message,
    is_candidate,
    is_error,
    make_candidate,
    make_error,
)

logger = logging.getLogger("recognizer")

# ---------------------------------------------------------------------------
# 引擎注册表：以后加 UniMERNet 只在这里加一行，recognize() 不动
# ---------------------------------------------------------------------------

ENGINE_PP_FORMULANET_L = "pp_formulanet_l"
ENGINE_UNIMERNET = "unimernet"  # 预留槽位，PP-FormulaNet 跑通后再填

ENGINES: Dict[str, Dict[str, Any]] = {
    ENGINE_PP_FORMULANET_L: {
        "model_name": os.environ.get("RECOGNIZER_MODEL", "PP-FormulaNet-L"),
    },
    # 第二模型接入后大概长这样（现在不要打开，会直接报 KeyError）：
    # ENGINE_UNIMERNET: {"model_name": "UniMERNet"},
}

DEFAULT_ENGINE = ENGINE_PP_FORMULANET_L
_DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models" / "PP-FormulaNet-L"

# 支持的后缀。与 CONTRACT.md §2.1 保持一致（C 那边接受 png/jpg/jpeg/gif/webp）。
_ALLOWED_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".pdf"}

# 多视角表：固定顺序，不用随机数。原图永远排第一，保证"单视角"就是原图。
# 视角越靠前，越可信；去重时保留先出现的那条。
_VIEW_OPS: Tuple[Tuple[str, Optional[Tuple[str, Any]]], ...] = (
    ("orig", None),
    ("zoom1.5", ("zoom", 1.5)),
    ("rot-2", ("rotate", -2.0)),
    ("rot2", ("rotate", 2.0)),
    ("binarize", ("binarize", None)),
)


def _max_candidates() -> int:
    try:
        return max(1, int(os.environ.get("RECOGNIZER_MAX_CANDIDATES", "6")))
    except ValueError:
        return 6


# ---------------------------------------------------------------------------
# 内部：配置读取
# ---------------------------------------------------------------------------


def _backend() -> str:
    return (os.environ.get("RECOGNIZER_BACKEND") or "paddle").strip().lower()


def _device() -> str:
    return (os.environ.get("RECOGNIZER_DEVICE") or "cpu").strip()


def _views_default_on() -> bool:
    return (os.environ.get("RECOGNIZER_VIEWS") or "off").strip().lower() in {"on", "1", "true", "yes"}


def _enabled_engines() -> List[str]:
    raw = os.environ.get("RECOGNIZER_ENGINES") or DEFAULT_ENGINE
    wanted = [x.strip() for x in raw.split(",") if x.strip()]
    enabled = [e for e in wanted if e in ENGINES]
    for unknown in set(wanted) - set(ENGINES):
        logger.warning("忽略未注册的引擎名: %s", unknown)
    return enabled or [DEFAULT_ENGINE]


# ---------------------------------------------------------------------------
# 内部：图片检查（把"文件不存在/损坏"这种错误在进模型之前就拦住）
# ---------------------------------------------------------------------------


def _check_image(image_path: Any) -> Tuple[Optional[str], Optional[str]]:
    """返回 (规范化后的路径, 错误信息)。二者必有一个为 None。"""
    if image_path is None:
        return None, "image_path 为空"
    try:
        path_str = os.fspath(image_path)
    except TypeError:
        return None, f"image_path 必须是路径字符串，收到 {type(image_path).__name__}"
    if isinstance(path_str, bytes):
        path_str = path_str.decode("utf-8", errors="replace")
    if not isinstance(path_str, str) or not path_str.strip():
        return None, "image_path 为空"

    path = Path(path_str).expanduser()
    if not path.exists():
        return None, f"图片不存在：{path}"
    if path.is_dir():
        return None, f"给的是目录不是图片文件：{path}"
    if path.suffix.lower() not in _ALLOWED_SUFFIX:
        return None, f"不支持的格式 {path.suffix}（支持 png/jpg/jpeg/bmp/webp/tif/tiff/pdf）"
    try:
        if path.stat().st_size == 0:
            return None, f"图片是空文件（0 字节）：{path}"
    except OSError as exc:
        return None, f"读不到图片信息：{exc}"

    # 有 PIL 就顺手校验一下能不能解码（装了 paddleocr 必然有 PIL）
    try:
        from PIL import Image
    except ImportError:
        pass
    else:
        try:
            with Image.open(path) as im:
                im.verify()
        except Exception as exc:  # noqa: BLE001 - 任何解码失败都算坏图
            return None, f"图片损坏无法解码：{type(exc).__name__}: {exc}"

    return str(path), None


# ---------------------------------------------------------------------------
# 内部：多视角生成（确定性）
# ---------------------------------------------------------------------------


def _apply_view_op(im: Any, op: Optional[Tuple[str, Any]], Image: Any) -> Any:
    """按固定规则生成一个视角的图。不引入任何随机性。"""
    if op is None:
        return im
    kind, arg = op
    if kind == "zoom":
        width, height = im.size
        size = (max(1, int(width * arg)), max(1, int(height * arg)))
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        return im.resize(size, resample)
    if kind == "rotate":
        return im.rotate(arg, expand=True, fillcolor=255)
    if kind == "binarize":
        return im.point(lambda pixel: 255 if pixel > 160 else 0)
    logger.warning("未知的视角操作 %s，忽略", kind)
    return im


@contextmanager
def _iter_views(image_path: str, thorough: bool) -> Iterator[List[Tuple[str, str]]]:
    """产出 [(图片路径, 视角名), ...]，第一个永远是原图。退出时清理临时文件。

    PDF、没装 PIL、或没开 thorough 时，只返回原图一张，行为与旧版一致。
    """
    views: List[Tuple[str, str]] = [(image_path, "orig")]
    tmpdir: Optional[str] = None

    if thorough and Path(image_path).suffix.lower() != ".pdf":
        try:
            from PIL import Image
        except ImportError:
            logger.warning("没装 PIL，无法生成多视角，退回只跑原图")
        else:
            try:
                tmpdir = tempfile.mkdtemp(prefix="rec_views_")
                with Image.open(image_path) as src:
                    gray = src.convert("L")
                    for name, op in _VIEW_OPS[1:]:
                        out = _apply_view_op(gray, op, Image)
                        out_path = os.path.join(tmpdir, f"{name}.png")
                        out.save(out_path)
                        views.append((out_path, name))
            except Exception as exc:  # noqa: BLE001 - 视角生成失败不该拖垮主流程
                logger.warning("多视角生成失败，退回只跑原图：%s: %s", type(exc).__name__, exc)
                views = [(image_path, "orig")]

    try:
        yield views
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 内部：模型加载（进程内只加载一次）
# ---------------------------------------------------------------------------

_MODEL_LOCK = threading.Lock()
_MODELS: Dict[Tuple[str, str, Optional[str], str], Any] = {}


def get_model(engine: str = DEFAULT_ENGINE) -> Any:
    """返回引擎对应的模型实例，首次调用时加载并缓存。

    Streamlit 每次交互都会把脚本从头跑一遍，如果每次都 new 一个模型，
    界面会卡几十秒。所以这里必须缓存；A 那边建议再包一层 @st.cache_resource。
    """
    cfg = ENGINES.get(engine)
    if cfg is None:
        raise KeyError(f"未注册的引擎：{engine}，已注册：{list(ENGINES)}")

    model_dir = os.environ.get("RECOGNIZER_MODEL_DIR")
    if not model_dir and cfg["model_name"] == "PP-FormulaNet-L" and _DEFAULT_MODEL_DIR.is_dir():
        model_dir = str(_DEFAULT_MODEL_DIR)
    model_kwargs = {"model_name": cfg["model_name"], "device": _device()}
    if model_dir:
        model_kwargs["model_dir"] = model_dir
    model_key = (engine, cfg["model_name"], model_dir, model_kwargs["device"])

    model = _MODELS.get(model_key)
    if model is not None:
        return model

    with _MODEL_LOCK:
        model = _MODELS.get(model_key)
        if model is not None:
            return model

        # 延迟导入：本机没装 paddle 时，import recognizer 不会立刻报错
        from paddleocr import FormulaRecognition

        started = time.time()
        model = FormulaRecognition(**model_kwargs)
        _MODELS[model_key] = model
        logger.info(
            "模型加载完成 engine=%s model=%s device=%s 耗时=%.1fs",
            engine,
            cfg["model_name"],
            _device(),
            time.time() - started,
        )
        return model


def warmup() -> None:
    """预热：A 可以在页面启动时调一次，避免用户第一次点按钮等半分钟。失败不抛异常。"""
    if _backend() == "mock":
        logger.warning("mock 模式，跳过模型预热")
        return
    for engine in _enabled_engines():
        try:
            get_model(engine)
        except Exception as exc:  # noqa: BLE001
            logger.error("预热失败 engine=%s：%s: %s", engine, type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# 内部：从 PaddleOCR 的 Result 对象里取 LaTeX
# ---------------------------------------------------------------------------


def _result_to_dict(result: Any) -> Dict[str, Any]:
    """把 Result 对象转成普通 dict。

    官方示例是 res.json → {'res': {'rec_formula': '...', 'input_path': ..., ...}}，
    不同小版本可能直接给 dict 或属性，这里全部兼容，避免升级就崩。
    """
    data = getattr(result, "json", None)
    if callable(data):
        try:
            data = data()
        except Exception:  # noqa: BLE001
            data = None
    if isinstance(data, dict):
        inner = data.get("res", data)
        return inner if isinstance(inner, dict) else {}
    return {}


def _extract_latex(result: Any) -> str:
    """取 LaTeX 字符串，**原样返回、不做 strip**。

    首尾空白属于"忠实转录"的一部分，交给 C 清理并记 trim_outer_whitespace（契约 §4.2）。
    取不到就返回空串，不自己编。
    """
    data = _result_to_dict(result)
    for key in ("rec_formula", "latex", "rec_text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _extract_score(result: Any) -> Optional[float]:
    """取置信度。公式识别模型默认不输出分数，取不到就是 None。"""
    data = _result_to_dict(result)
    for key in ("rec_score", "score"):
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


# ---------------------------------------------------------------------------
# 内部：跑单个引擎（单张图）
# ---------------------------------------------------------------------------


def _mock_candidate(engine: str, image_path: str) -> Candidate:
    logger.warning("RECOGNIZER_BACKEND=mock，仅用于联调，返回失败候选：%s", image_path)
    return make_error(engine, "mock backend is not a recognition result")


def _run_engine(engine: str, image_path: str) -> List[Candidate]:
    """跑一个引擎的一张图，无论成败都返回非空 list。

    latency_ms 是这次 predict 的实测墙钟时间（首次调用会包含模型加载，
    那是真实延迟，不美化）。失败时 latex 为空、原因放 error，由 C 跳过。
    """
    started = time.perf_counter()
    try:
        if _backend() == "mock":
            return [_mock_candidate(engine, image_path)]

        model = get_model(engine)
        # 先物化成 list：predict 可能返回生成器，边消费边计时会低估耗时
        results = list(model.predict(input=image_path, batch_size=1))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        candidates: List[Candidate] = []
        for result in results:
            candidates.append(
                make_candidate(
                    engine,
                    _extract_latex(result),
                    _extract_score(result),
                    latency_ms=elapsed_ms,
                )
            )

        if not candidates:
            return [make_error(engine, "模型没有返回任何结果（predict 返回空列表）", elapsed_ms)]

        logger.debug(
            "识别完成 engine=%s 候选数=%d 耗时=%.0fms img=%s",
            engine,
            len(candidates),
            elapsed_ms,
            image_path,
        )
        return candidates

    except Exception as exc:  # noqa: BLE001 - B 的边界，任何异常都转成失败候选
        logger.exception("识别失败 engine=%s img=%s", engine, image_path)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return [make_error(engine, f"{type(exc).__name__}: {exc}", elapsed_ms)]


# ---------------------------------------------------------------------------
# 内部：去重 / 记录
# ---------------------------------------------------------------------------


def _latex_key(latex: str) -> str:
    """去重用的比较键，对齐 CONTRACT.md §2.2：按 `strip()` 后的完整字符串比较。

    只去掉首尾空白，**不折叠内部空白**：`x ^ 2` 与 `x^2` 算两条（语义等价判断属于
    C 的树结构分析，B 不做）。
    """
    return latex.strip()


def _log_jsonl(payload: Dict[str, Any]) -> None:
    target = os.environ.get("RECOGNIZER_LOG_JSONL")
    if not target:
        return
    try:
        path = Path(target).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - 记日志失败绝不能影响识别
        logger.warning("写 JSONL 日志失败：%s", exc)


# ---------------------------------------------------------------------------
# 对外唯一入口
# ---------------------------------------------------------------------------


def recognize(image_path: str, *, thorough: bool = False) -> List[Dict]:
    """图片路径 → LaTeX 候选列表。

    参数:
        image_path: 本地图片（或 PDF）路径
        thorough:   是否用多视角扩候选池（慢 3~5 倍，默认关闭）。
                    A 的推荐用法：先 recognize(path) 快速出结果，C 报 need_review
                    之后再 recognize(path, thorough=True) 补一批候选重判。

    返回:
        list[dict]，每项 5 个字段（engine / latex / score / latency_ms / error），
        已按"引擎顺序 × 视角顺序"排好，去重后最多 MAX_CANDIDATES 条。
        出错时返回 [{"engine": ..., "latex": "", "score": None,
                     "latency_ms": ..., "error": "原因"}]。
    """
    path, error = _check_image(image_path)
    if error is not None:
        logger.error("图片检查未通过：%s", error)
        return [make_error(DEFAULT_ENGINE, error)]

    use_views = thorough or _views_default_on()
    started = time.time()
    candidates: List[Candidate] = []
    seen: Dict[Tuple[str, str], int] = {}  # (引擎, LaTeX) → 命中次数（只进日志）
    origin: Dict[Tuple[str, str], List[str]] = {}  # (引擎, LaTeX) → 命中的视角名
    errors: List[str] = []
    error_latency = 0.0
    blanks = 0
    view_count = 1

    with _iter_views(path, use_views) as views:  # type: ignore[arg-type]
        view_count = len(views)
        for engine in _enabled_engines():
            for view_path, view_name in views:
                for item in _run_engine(engine, view_path):
                    if is_error(item):
                        # 失败候选不进候选池：个别视角失败不代表这张图识别不了
                        errors.append(f"{engine}@{view_name}: {error_message(item)}")
                        error_latency = max(error_latency, float(item.get("latency_ms") or 0.0))
                        continue
                    if not item["latex"].strip():
                        # 纯空白按契约交由 C 跳过，B 也不放进池子
                        blanks += 1
                        continue
                    key = (engine, _latex_key(item["latex"]))
                    if key in seen:
                        seen[key] += 1
                        origin[key].append(view_name)
                        continue
                    seen[key] = 1
                    origin[key] = [view_name]
                    candidates.append(item)

    if not candidates:
        if errors:
            detail = "；".join(errors)
        elif blanks:
            detail = f"模型没有识别出任何内容（{blanks} 次结果均为空白）"
        else:
            detail = "所有视角都返回空结果"
        logger.error("没有拿到任何可用候选：%s", detail)
        return [make_error(DEFAULT_ENGINE, detail, error_latency)]

    if len(candidates) > _max_candidates():
        logger.warning(
            "候选数 %d 超过上限 %d，只保留靠前的（原图视角优先）",
            len(candidates),
            _max_candidates(),
        )
        candidates = candidates[: _max_candidates()]

    # 自检：保证交出去的东西符合契约（真出问题也只记日志，不改数据结构）
    for item in candidates:
        if not is_candidate(item):
            logger.error("产生了不符合契约的候选：%r", item)

    elapsed = time.time() - started
    logger.info(
        "识别完成 视角=%d 引擎=%s 候选=%d 耗时=%.2fs img=%s",
        view_count,
        ",".join(_enabled_engines()),
        len(candidates),
        elapsed,
        path,
    )
    if errors:
        logger.warning("有 %d 个视角/引擎失败：%s", len(errors), " | ".join(errors[:3]))

    _log_jsonl(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "image": path,
            "views": view_count,
            "thorough": use_views,
            "engines": _enabled_engines(),
            "backend": _backend(),
            "elapsed_sec": round(elapsed, 3),
            "candidates": [
                {
                    "engine": c["engine"],
                    "latex": c["latex"],
                    "latency_ms": c["latency_ms"],
                    "hits": seen.get((c["engine"], _latex_key(c["latex"])), 1),
                    "views": origin.get((c["engine"], _latex_key(c["latex"])), []),
                }
                for c in candidates
            ],
            "blank_results": blanks,
            "errors": errors,
        }
    )

    return candidates


# ---------------------------------------------------------------------------
# 模块内自测：不依赖 A / C，单独就能跑
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    default_img = Path(__file__).parent / "samples" / "sample_plus.png"
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else str(default_img)
    thorough_flag = "--thorough" in sys.argv

    print(f"输入：{target}")
    print(f"后端：{_backend()}   设备：{_device()}   引擎：{_enabled_engines()}")
    print(f"多视角：{'开' if thorough_flag else '关'}")
    print(json.dumps(recognize(target, thorough=thorough_flag), ensure_ascii=False, indent=2))
