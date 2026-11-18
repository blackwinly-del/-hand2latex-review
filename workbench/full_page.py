import json
import logging
import os
import threading
import time
from pathlib import Path

from openai import OpenAI

from reasoning.context import _read_image_data_url

logger = logging.getLogger("workbench.full_page")

_CLIENT_LOCK = threading.Lock()
_CLIENTS: dict[tuple, OpenAI] = {}


def _llm_config() -> tuple[str, str | None, float]:
    """统一读取并校验 OpenAI 兼容配置（fix.py 与整页识别共用）。"""
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    if not api_key or not api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not model or not model.strip():
        raise RuntimeError("OPENAI_MODEL is not configured")
    base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
    raw_timeout = os.environ.get("FULLPAGE_TIMEOUT_SECONDS", "120")
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise RuntimeError("FULLPAGE_TIMEOUT_SECONDS must be a number") from None
    return api_key.strip(), base_url, timeout


def _model_name() -> str:
    """读取已校验的模型名（与 _llm_config 的校验口径一致）。"""
    model = (os.environ.get("OPENAI_MODEL") or "").strip()
    if not model:
        raise RuntimeError("OPENAI_MODEL is not configured")
    return model


def _client() -> OpenAI:
    """返回共享的 OpenAI 客户端；同一配置只创建一次，避免每次请求重建连接。"""
    api_key, base_url, timeout = _llm_config()
    cache_key = (api_key, base_url, timeout)
    client = _CLIENTS.get(cache_key)
    if client is not None:
        return client
    with _CLIENT_LOCK:
        client = _CLIENTS.get(cache_key)
        if client is None:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            _CLIENTS[cache_key] = client
        return client


# ctex 支持的 fontset 取值，白名单用于防止把任意字符串拼进 LaTeX preamble。
# windows 依赖系统安装的 SimHei/SimSun 等中文字体；fandol 随 TeX 发行版分发，
# 不依赖系统字体，适合没有预装 CJK 字体的环境（如 CI runner、Linux）。
_ALLOWED_FONTSETS = frozenset({"windows", "mac", "adobe", "ubuntu", "fandol", "none"})


def _ctex_fontset() -> str:
    """返回 ctex 的 fontset 配置，默认 windows，可用 LATEX_FONTSET 覆盖。"""
    fontset = (os.environ.get("LATEX_FONTSET") or "windows").strip().lower()
    if fontset not in _ALLOWED_FONTSETS:
        raise RuntimeError(
            f"LATEX_FONTSET must be one of {sorted(_ALLOWED_FONTSETS)}, got {fontset!r}"
        )
    return fontset


def _ctex_documentclass() -> str:
    """生成 ctexart 的 documentclass 行（build_tex 与真实编译测试共用）。"""
    return r"\documentclass[UTF8,fontset=" + _ctex_fontset() + r"]{ctexart}"


def _escape_text(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "^": r"\^{}",
        "~": r"\~{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def build_tex(document: dict) -> str:
    title = document.get("title") or "手写笔记"
    blocks = document.get("blocks")
    if not isinstance(title, str):
        raise TypeError("document title must be a string")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("document blocks must not be empty")

    parts = [
        _ctex_documentclass(),
        r"\usepackage{amsmath,amssymb}",
        r"\usepackage{graphicx}",
        r"\usepackage[margin=2.2cm]{geometry}",
        r"\title{" + _escape_text(title) + "}",
        r"\begin{document}",
        r"\maketitle",
    ]
    for block in blocks:
        if not isinstance(block, dict):
            raise TypeError("each block must be a dict")
        block_type = block.get("type")
        if block_type == "page_break":
            parts.extend([r"\newpage", ""])
        elif block_type == "blank_page":
            parts.extend([r"\null", ""])
        elif block_type == "paragraph":
            text = block.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("paragraph text must not be blank")
            parts.extend([_escape_text(text), ""])
        elif block_type == "display_formula":
            latex = block.get("latex")
            if not isinstance(latex, str) or not latex.strip():
                raise ValueError("formula latex must not be blank")
            parts.extend(["\\[", latex.strip(), "\\]", ""])
        elif block_type == "figure":
            description = block.get("description")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("figure description must not be blank")
            escaped = _escape_text(description)
            parts.extend(
                [
                    r"\begin{figure}[htbp]",
                    r"\centering",
                    r"\fbox{\parbox{0.85\linewidth}{原始示意图（未重新绘制）：" + escaped + "}}",
                    r"\caption{" + escaped + "}",
                    r"\end{figure}",
                    "",
                ]
            )
        else:
            raise ValueError(f"unsupported block type: {block_type}")
    parts.append(r"\end{document}")
    return "\n".join(parts) + "\n"


def merge_documents(documents: list[dict]) -> dict:
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must not be empty")

    merged_blocks = []
    for index, document in enumerate(documents):
        blocks = document.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("each page must contain a non-empty blocks array")
        if index:
            merged_blocks.append({"type": "page_break"})
        merged_blocks.extend(blocks)

    title = documents[0].get("title") or "手写笔记"
    return {"title": title, "blocks": merged_blocks}


class _PageResponseError(ValueError):
    """整页响应为空、被截断或不是合法 JSON——值得放宽 token 预算重试一次。"""


def _call_page_model(image_path: str, max_tokens: int) -> dict:
    completion = _client().chat.completions.create(
        model=_model_name(),
        messages=[
            {
                "role": "system",
                "content": (
                    "Return the JSON object directly and keep analysis brief. "
                    "Transcribe one handwritten mixed-note page into ordered blocks. "
                    "Preserve Chinese text and mathematical notation faithfully; do not solve, "
                    "correct, complete, or simplify. Do not invent figure contents. Return only "
                    "JSON with a string title and a non-empty blocks array. Each block must be "
                    "one of: {\"type\":\"paragraph\",\"text\":\"...\"}, "
                    "{\"type\":\"display_formula\",\"latex\":\"...\"}, "
                    "{\"type\":\"figure\",\"description\":\"...\"}, or "
                    "{\"type\":\"blank_page\"}. Use display_formula for standalone formulas and "
                    "figure only for actual drawings. Return one blank_page block and no content "
                    "blocks only when the image contains no handwritten text, formulas, or drawings."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this full handwritten page in reading order."},
                    {"type": "image_url", "image_url": {"url": _read_image_data_url(image_path)}},
                ],
            },
        ],
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    choice = completion.choices[0]
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise _PageResponseError(f"full-page response content is empty (finish_reason={choice.finish_reason})")
    if choice.finish_reason == "length":
        raise _PageResponseError("full-page response was truncated by max_tokens")
    try:
        document = json.loads(content)
    except json.JSONDecodeError as error:
        raise _PageResponseError(
            f"full-page response was not valid JSON "
            f"(finish_reason={choice.finish_reason}, length={len(content)})"
        ) from error
    if not isinstance(document, dict):
        raise TypeError("full-page response must be a JSON object")
    return document


def _request_page(image_path: str) -> dict:
    """整页识别请求，带一次放宽 token 预算的重试。

    背景：真实多页评估中 page_3 曾因推理 token 耗尽输出预算而返回空内容，
    放宽后重试成功（见 artifacts/multipage_real/report_initial_real.json）。
    只有响应形状问题（空内容 / 截断 / 非 JSON）才重试；配置错误和网络异常
    重试没有意义，直接抛出。
    """
    base_tokens = int(os.environ.get("FULLPAGE_MAX_TOKENS", "24000"))
    budget = base_tokens
    last_error: _PageResponseError | None = None
    for attempt in (1, 2):
        try:
            return _call_page_model(image_path, max_tokens=budget)
        except _PageResponseError as error:
            last_error = error
            if attempt == 1:
                budget = int(base_tokens * 1.5)
                logger.warning(
                    "整页识别第 1 次尝试失败：%s；放宽 token 预算（%d → %d）后重试一次",
                    error,
                    base_tokens,
                    budget,
                )
    assert last_error is not None
    raise last_error


def generate_document(image_path: str) -> dict:
    started = time.perf_counter()
    document = _request_page(image_path)
    tex = build_tex(document)
    return {
        "title": document.get("title") or "手写笔记",
        "blocks": document["blocks"],
        "tex": tex,
        "model": _model_name(),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "human_review": "required",
        "source_image": str(Path(image_path)),
    }
