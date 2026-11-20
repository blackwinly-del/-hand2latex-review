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
from recognizer import recognize, warmup  # noqa: E402  （B 层：图片 → LaTeX 候选）

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# 画布画笔默认白色背景、黑色笔迹（对识别最友好）。
_CANVAS_WIDTH = 720
_CANVAS_HEIGHT = 320
_STROKE_WIDTH = 3

# 停笔判定阈值（秒）：画笔内容保持不变达到该时长即触发识别。
_IDLE_SECONDS = 1.0

# 识别结果临时图片的存放目录（在仓库 artifacts 下，避免污染源码目录）。
_IMAGE_DIR = _PROJECT_ROOT / "artifacts" / "demo"
_IMAGE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 模型缓存：Streamlit 每次交互都会重跑脚本，必须复用模型实例，否则每次等几十秒。
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _get_model(engine: str) -> None:
    """触发 B 层的模型加载（进程内缓存）。返回值本身不用，只保证加载完成。"""
    warmup()
    return None


def _backend() -> str:
    return (os.environ.get("RECOGNIZER_BACKEND") or "paddle").strip().lower()


# ---------------------------------------------------------------------------
# 停笔判定：比较画笔对象指纹，内容稳定满 1 秒才触发识别。
# ---------------------------------------------------------------------------

def _canvas_fingerprint(canvas_result) -> str | None:
    """对画布内容做指纹。无笔迹时返回 None。"""
    if canvas_result is None or canvas_result.json_data is None:
        return None
    objects = canvas_result.json_data.get("objects") or []
    if not objects:
        return None
    # 用 path 坐标序列化，能捕捉到"同一笔画还在继续延长"的变化。
    # Fabric.js 的 path 每段形如 ["M", x, y] / ["Q", ...]，首元素是命令字母，
    # 不能直接 float()，否则一画就 ValueError: could not convert string to float: 'M'。
    serialized = []
    for obj in objects:
        coords = []
        for segment in (obj.get("path") or []):
            numeric = []
            for value in segment:
                try:
                    numeric.append(round(float(value), 1))
                except (TypeError, ValueError):
                    continue  # 跳过 'M'/'L'/'Q' 等路径命令字母，只留坐标
            if numeric:
                coords.append(tuple(numeric))
        serialized.append((obj.get("type"), coords))
    return hashlib.sha1(repr(serialized).encode("utf-8")).hexdigest()


def _idle_elapsed(fingerprint: str | None) -> float:
    """返回当前指纹已保持稳定的时长（秒）。指纹变化则重新计时。"""
    state = st.session_state
    if "_fp_since" not in state or fingerprint != state.get("_last_fp"):
        state["_last_fp"] = fingerprint
        state["_fp_since"] = time.time()
    return time.time() - state["_fp_since"]


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
    path = _IMAGE_DIR / "canvas_latest.png"
    background.save(path)
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
    st.caption(f"识别设备：{device_label}。首次识别要加载模型，GPU 约十几秒，CPU 更久。")

# 预热模型（首次加载，mock 模式自动跳过）。放在列布局之前，避免渲染时再加载。
if backend != "mock":
    _get_model("pp_formulanet_l")

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

# ---------------------------------------------------------------------------
# 停笔自动识别：内容稳定满 1 秒且尚未识别过该指纹时触发。
# ---------------------------------------------------------------------------

fingerprint = _canvas_fingerprint(canvas_result)
idle = _idle_elapsed(fingerprint)

if fingerprint is not None and idle >= _IDLE_SECONDS:
    if st.session_state.get("_recognized_fp") != fingerprint:
        with st.spinner("正在识别…"):
            try:
                image_path = _canvas_to_png(canvas_result)
                if image_path is None:
                    result = None
                else:
                    result = _run_recognition(image_path)
            except Exception as exc:  # noqa: BLE001 - 识别失败不拖垮页面，友好展示
                result = {"error": f"{type(exc).__name__}: {exc}"}
        st.session_state["_recognized_fp"] = fingerprint
        st.session_state["_last_result"] = result
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

        col1, col2 = st.columns(2)
        col1.metric("置信度", confidence)
        col2.metric("需人工复核", "是" if need_review else "否")

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
- **真实识别**：需要安装 `requirements-b.txt`（paddlepaddle + paddleocr）并准备
  `models/PP-FormulaNet-L` 模型权重（首次运行可自动下载）。
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
