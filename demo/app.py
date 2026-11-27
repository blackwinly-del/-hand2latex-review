"""Hand2LaTeX 画板 + 动态手写公式识别演示（Streamlit）。

杀手锏：不用点「上传」或「识别」按钮。在左侧画板上用鼠标写一个公式（如 F = ma），
停笔约 1 秒后，右侧自动把手写内容识别成漂亮的 LaTeX 排版。

调用链：
    st_canvas 画板 → 导出 PNG → recognizer.recognize()（B 层，PaddleOCR + PP-FormulaNet）
    → reasoner.refine()（C 层，规范化 / 去重 / 结构检查）→ st.latex 渲染

依赖：
    pip install -r requirements-demo.txt
启动：
    streamlit run demo/app.py

识别引擎默认用真实模型（PP-FormulaNet-L）。没有 paddle 环境时，设环境变量
RECOGNIZER_BACKEND=mock 即可跑通完整交互（识别结果会是占位失败候选，仅供联调）。
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np
import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

# 把仓库根目录加入 sys.path，使 demo 能 import 根目录下的 B / C 层模块。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from reasoner import refine  # noqa: E402  （C 层：候选 → 规范化 / 去重 / 结构检查）
from recognizer import ENGINES, recognize, warmup  # noqa: E402  （B 层：图片 → LaTeX 候选）

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# 画布画笔默认白色背景、黑色笔迹（对识别最友好）。
_CANVAS_WIDTH = 720
_CANVAS_HEIGHT = 320
_STROKE_WIDTH = 3

# 停笔判定阈值（秒）：画笔内容保持不变达到该时长即触发识别。
_IDLE_SECONDS = 1.0

# 模型档位。PP-FormulaNet-L 最准但 CPU 上单张 6~8 秒；
# -S 快得多（体积约为 L 的 1/5），适合演示和反复试写的场景。
# 识别前会用 _crop_to_ink 裁掉大片空白，这也是最有效的提速手段之一。
_MODEL_CHOICES = {
    "快速（PP-FormulaNet-S，演示推荐）": "PP-FormulaNet-S",
    "精准（PP-FormulaNet-L，默认）": "PP-FormulaNet-L",
}
_DEFAULT_MODEL_LABEL = "快速（PP-FormulaNet-S，演示推荐）"

# 识别结果临时图片的存放目录（在仓库 artifacts 下，避免污染源码目录）。
_IMAGE_DIR = _PROJECT_ROOT / "artifacts" / "demo"
_IMAGE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 模型缓存：Streamlit 每次交互都会重跑脚本，必须复用模型实例，否则每次等几十秒。
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _get_model(engine: str, model_name: str) -> None:
    """按 (引擎, 模型名) 加载并缓存模型。

    切换档位时会加载另一份模型（各自缓存），不会反复重建；
    recognizer.get_model 的缓存 key 里包含 model_name，所以这里可以放心改 ENGINES。
    """
    ENGINES[engine]["model_name"] = model_name
    warmup()
    return None


def _backend() -> str:
    return (os.environ.get("RECOGNIZER_BACKEND") or "paddle").strip().lower()


# ---------------------------------------------------------------------------
# 停笔判定：比较画笔对象指纹，内容稳定满 1 秒才触发识别。
# ---------------------------------------------------------------------------

def _normalize_path(path) -> tuple:
    """把 Fabric.js 的 path 规整成可哈希、可比较的结构。

    Fabric.js 的 path 是 SVG 命令序列，元素形如 ["M", 12.3, 45.6] /
    ["L", x, y] / ["Q", x1, y1, x2, y2]，**第一个元素是命令字母**，
    其余才是坐标。把整段当数字 float() 会在写到第一笔时抛
    ValueError: could not convert string to float: 'M'。
    """
    points = []
    for seg in path or []:
        if not isinstance(seg, (list, tuple)) or not seg:
            continue
        head = seg[0]
        if isinstance(head, str):
            # 标准情况：命令字母 + 若干坐标
            coords = []
            for value in seg[1:]:
                try:
                    coords.append(round(float(value), 1))
                except (TypeError, ValueError):
                    coords.append(str(value))
            points.append((head, tuple(coords)))
        else:
            # 少数版本可能直接给纯数字数组，兜底处理
            try:
                points.append(("", tuple(round(float(value), 1) for value in seg)))
            except (TypeError, ValueError):
                points.append(("", tuple(str(value) for value in seg)))
    return tuple(points)


def _canvas_fingerprint(canvas_result) -> str | None:
    """对画布内容做指纹。无笔迹时返回 None。"""
    if canvas_result is None or canvas_result.json_data is None:
        return None
    objects = canvas_result.json_data.get("objects") or []
    if not objects:
        return None
    # 用 path 命令序列做指纹，能捕捉到"同一笔画还在继续延长"的变化。
    # 命令字母（M/L/Q）由 _normalize_path 单独保留，不参与 float() 转换，
    # 否则写到第一笔就会 ValueError: could not convert string to float: 'M'。
    serialized = [
        (obj.get("type"), _normalize_path(obj.get("path")))
        for obj in objects
        if isinstance(obj, dict)
    ]
    return hashlib.sha1(repr(serialized).encode("utf-8")).hexdigest()


def _idle_elapsed(fingerprint: str | None) -> float:
    """返回当前指纹已保持稳定的时长（秒）。指纹变化则重新计时。

    注意：空画布时 fingerprint 是 None，而 session_state.get 的缺省值也是 None，
    两者相等会让「首次进入」被误判成「指纹未变化」，从而读不到 _fp_since
    （KeyError）。所以必须先显式判断 key 是否存在。
    """
    state = st.session_state
    if "_fp_since" not in state or fingerprint != state.get("_last_fp"):
        state["_last_fp"] = fingerprint
        state["_fp_since"] = time.time()
        return 0.0
    return time.time() - state["_fp_since"]


def _crop_to_ink(image: Image.Image, padding: int = 24) -> Image.Image:
    """裁到笔迹包围盒（留 padding 边距）。

    画布 720×320，但用户写的公式往往只占中间一小块。直接把整张空白图喂给模型，
    CPU 上白白多算好几秒；裁到笔迹范围能显著缩短推理时间，也避免大片空白干扰识别。
    """
    # 转灰度后反相：白底(255)变0、笔迹变高值，用 getbbox 拿到非零区域。
    gray = image.convert("L")
    ink_mask = gray.point(lambda pixel: 255 if pixel < 250 else 0)
    box = ink_mask.getbbox()
    if box is None:
        return image
    left, top, right, bottom = box
    width, height = image.size
    return image.crop(
        (
            max(0, left - padding),
            max(0, top - padding),
            min(width, right + padding),
            min(height, bottom + padding),
        )
    )


def _canvas_to_png(canvas_result) -> Path | None:
    """把画布的 RGBA 图像落盘成 PNG，返回路径；无笔迹返回 None。"""
    if canvas_result is None or canvas_result.image_data is None:
        return None
    if _canvas_fingerprint(canvas_result) is None:
        return None
    image = Image.fromarray(canvas_result.image_data.astype(np.uint8))
    # 转成白底、RGB（去掉透明通道，识别更稳）。
    background = Image.new("RGB", image.size, (255, 255, 255))
    if image.mode == "RGBA":
        background.paste(image, mask=image.split()[3])
    else:
        background.paste(image.convert("RGB"))
    # 裁掉大片空白：输入更小，推理更快，也减少空白对识别的干扰。
    cropped = _crop_to_ink(background)
    path = _IMAGE_DIR / "canvas_latest.png"
    cropped.save(path)
    return path


def _run_recognition(image_path: Path) -> dict:
    """B 识别 + C 规范化，返回 refine 的结果 dict。"""
    candidates = recognize(str(image_path))
    return refine(str(image_path), candidates)


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Hand2LaTeX 动态识别", page_icon="✍️", layout="wide")
st.title("✍️ Hand2LaTeX —— 画板 + 动态手写公式识别")
st.caption(
    "用鼠标在左侧画板写一个物理/数学公式（比如 **F = ma**），停笔约 1 秒，"
    "右侧自动识别并排版成 LaTeX。**无需点任何按钮。**"
)

# 后端提示：mock 模式给出醒目的联调说明。
backend = _backend()
if backend == "mock":
    st.warning(
        "当前 `RECOGNIZER_BACKEND=mock`，识别结果只是占位失败候选（用于联调）。"
        "接入真实模型请去掉该环境变量并安装 `requirements-b.txt`。"
    )
else:
    device = (os.environ.get("RECOGNIZER_DEVICE") or "cpu").strip()
    device_label = f"GPU（{device}）" if device.lower().startswith("gpu") else "CPU"
    model = (os.environ.get("RECOGNIZER_MODEL") or "PP-FormulaNet-L").strip()
    st.caption(
        f"识别模型：{model} · 设备：{device_label}。画板可以立刻开始写；"
        "模型在第一次识别时才加载（GPU 实测约 50 秒），届时右侧会显示加载进度。"
    )

left, right = st.columns([1, 1])

with left:
    st.subheader("🖊️ 手写画板")
    canvas_result = st_canvas(
        stroke_width=_STROKE_WIDTH,
        stroke_color="#000000",
        background_color="#ffffff",
        height=_CANVAS_HEIGHT,
        width=_CANVAS_WIDTH,
        drawing_mode="freedraw",
        update_streamlit=True,
        return_image_data=True,
        key="formula_canvas",
    )

with right:
    st.subheader("✨ 识别结果")
    result_placeholder = st.empty()

# 模型档位放在侧边栏，切换后旧档位的模型仍留在缓存里，切回来不用重新加载。
model_label = st.sidebar.radio(
    "识别模型",
    list(_MODEL_CHOICES),
    index=list(_MODEL_CHOICES).index(_DEFAULT_MODEL_LABEL),
    help="快速档用 PP-FormulaNet-S，CPU 上明显更快；精准档用 -L，更准但慢。",
)
model_name = _MODEL_CHOICES[model_label]

# 模型不在这里加载。放到画布之后、真正识别之前：GPU 首次加载实测约 50 秒，
# 放在画布之前会让页面半分钟没有画板，看起来就是"画板加载不出来"。

# ---------------------------------------------------------------------------
# 停笔自动识别：内容稳定满 1 秒且尚未识别过该指纹时触发。
# ---------------------------------------------------------------------------

fingerprint = _canvas_fingerprint(canvas_result)
idle = _idle_elapsed(fingerprint)

# 识别结果缓存：指纹 + 模型档位 → 结果。擦掉重画回原样、或切档后切回来，都直接复用。
result_cache = st.session_state.setdefault("_result_cache", {})
cache_key = (fingerprint, model_name)

if fingerprint is not None and idle >= _IDLE_SECONDS:
    if cache_key in result_cache:
        # 命中缓存：直接用上次结果，不再调模型。
        st.session_state["_last_result"] = result_cache[cache_key]
        st.session_state["_recognized_fp"] = fingerprint
    elif st.session_state.get("_recognized_fp") != fingerprint or (
        st.session_state.get("_recognized_model") != model_name
    ):
        started = time.perf_counter()
        if backend != "mock" and st.session_state.get("_loaded_model") != model_name:
            # 首次识别、或切了模型档位时才加载。画板此时早已画出来，用户看着进度等。
            with st.spinner(f"首次识别要加载 {model_name}（GPU 约 50 秒，请稍候）…"):
                _get_model("pp_formulanet_l", model_name)
            st.session_state["_loaded_model"] = model_name
        with st.spinner("正在识别…"):
            try:
                image_path = _canvas_to_png(canvas_result)
                if image_path is None:
                    result = None
                else:
                    result = _run_recognition(image_path)
            except Exception as exc:  # noqa: BLE001 - 识别失败不拖垮页面，友好展示
                result = {"error": f"{type(exc).__name__}: {exc}"}
        elapsed = time.perf_counter() - started
        st.session_state["_recognized_fp"] = fingerprint
        st.session_state["_recognized_model"] = model_name
        st.session_state["_last_result"] = result
        st.session_state["_last_elapsed"] = elapsed
        result_cache[cache_key] = result
else:
    # 还没到停笔阈值时，不清空上一次结果，只显示提示。
    if fingerprint is None:
        result_placeholder.info("画板还是空的——试着写点什么吧。")
    else:
        remaining = max(0.0, _IDLE_SECONDS - idle)
        result_placeholder.info(f"正在等待停笔…（{remaining:.1f} 秒后自动识别）")

result = st.session_state.get("_last_result")

with right:
    if result is None:
        pass  # 已有上面的占位提示
    elif "error" in result and result["error"]:
        result_placeholder.error(f"识别失败：{result['error']}")
    else:
        final_latex = result.get("final_latex") or ""
        confidence = result.get("confidence") or "low"
        need_review = result.get("need_review", True)

        result_placeholder.empty()
        st.markdown("#### 识别出的 LaTeX")
        if final_latex:
            # st.latex 用 KaTeX 渲染，是"手写 → 漂亮排版"的视觉高潮。
            st.latex(final_latex)
            st.code(final_latex, language="latex")
        else:
            st.warning("没有识别出内容。")

        col1, col2, col3 = st.columns(3)
        col1.metric("置信度", confidence)
        col2.metric("需人工复核", "是" if need_review else "否")
        elapsed = st.session_state.get("_last_elapsed")
        col3.metric("识别耗时", f"{elapsed:.1f}s" if elapsed else "—")

        if result.get("changes"):
            with st.expander("规范化改动（C 层）"):
                for change in result["changes"]:
                    st.markdown(
                        f"- **{change['rule']}**：`{change.get('before', '')}` → "
                        f"`{change.get('after', '')}`"
                    )

with st.expander("ℹ️ 使用说明 / 环境要求"):
    st.markdown(
        """
- **怎么玩**：左侧画板用鼠标写公式，停笔约 1 秒，右侧自动出 LaTeX 排版。
- **识别慢怎么办**：侧边栏切「快速」档（PP-FormulaNet-S），CPU 上比 -L 快数倍；
  识别前会自动裁掉画布空白区域，也在提速。
- **真实识别**：需要安装 `requirements-b.txt`（paddlepaddle + paddleocr）并准备
  `models/PP-FormulaNet-L` 模型权重（首次运行可自动下载；-S 档会自动下载对应权重）。
- **仅联调**：设 `RECOGNIZER_BACKEND=mock` 可跳过模型，跑通完整交互流程。
- **清空重画**：画板自带工具栏的橡皮/撤销，或刷新页面。
        """
    )

# 画布停止更新后 Streamlit 不会自己重跑，idle 会一直停在 0，"停笔自动识别"永远不触发。
# 有笔迹、还没到停笔阈值、且这个指纹还没识别过时，等 0.25 秒重跑一次，直到越过阈值。
# 识别完成后 _recognized_fp 等于当前指纹，这里就不再重跑，页面安静下来。
if (
    fingerprint is not None
    and idle < _IDLE_SECONDS
    and st.session_state.get("_recognized_fp") != fingerprint
):
    time.sleep(0.25)
    st.rerun()
