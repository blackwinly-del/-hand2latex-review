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


# 整页模型有时会在正文里直接写 ∈、≤ 这类 Unicode 符号；ctex 正文的单字节字体
# 没有这些字形，编译后就是缺字。这里只做编码转换，不改变任何数学含义。
_UNICODE_MATH = {
    "∈": r"\in",
    "∉": r"\notin",
    "≤": r"\le",
    "≥": r"\ge",
    "≠": r"\neq",
    "≈": r"\approx",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "∞": r"\infty",
    "π": r"\pi",
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "θ": r"\theta",
    "λ": r"\lambda",
    "μ": r"\mu",
    "σ": r"\sigma",
    "φ": r"\phi",
    "ω": r"\omega",
    "Ω": r"\Omega",
    "→": r"\rightarrow",
    "←": r"\leftarrow",
    "↔": r"\leftrightarrow",
    "×": r"\times",
    "÷": r"\div",
    "±": r"\pm",
}

_TEXT_REPLACEMENTS = {
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


def _convert_math_unicode(text: str) -> str:
    """把数学片段里的 Unicode 符号换成命令；控制词后紧跟字母时补空格。"""
    converted = []
    for index, char in enumerate(text):
        command = _UNICODE_MATH.get(char)
        if command is None:
            converted.append(char)
            continue
        converted.append(command)
        following = text[index + 1] if index + 1 < len(text) else ""
        if following.isalpha():
            converted.append(" ")
    return "".join(converted)


def _looks_like_inline_math(text: str) -> bool:
    """成对的 $ 才当作公式；含中文或空内容的多半是货币/普通文字，按字面转义。"""
    return bool(text.strip()) and "\n" not in text and not any(
        "\u4e00" <= char <= "\u9fff" for char in text
    )


def _find_closing_dollar(text: str, start: int) -> int:
    index = start
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "$":
            return index
        index += 1
    return -1


def _escape_plain(text: str) -> str:
    """转义普通文字，但把其中的 Unicode 数学符号包成行内公式。"""
    escaped = []
    for char in text:
        command = _UNICODE_MATH.get(char)
        if command is not None:
            escaped.append("$" + command + "$")
        else:
            escaped.append(_TEXT_REPLACEMENTS.get(char, char))
    return "".join(escaped)


def _escape_text(text: str) -> str:
    """转义普通段落/标题，但原样保留模型给出的成对行内公式。

    整页模型可能把行内公式写成 ``$x^2$``；旧实现把 $ 一并转义成 ``\\$``，
    PDF 里就会出现字面反斜杠。落单的 $（例如价格 ``$5``）仍然按普通字符转义。
    """
    parts = []
    plain: list[str] = []
    index = 0
    length = len(text)

    def flush_plain() -> None:
        if plain:
            parts.append(_escape_plain("".join(plain)))
            plain.clear()

    while index < length:
        char = text[index]
        if char == "\\" and index + 1 < length and text[index + 1] == "$":
            plain.append("$")
            index += 2
            continue

        if char == "$":
            if text.startswith("$$", index):
                end = text.find("$$", index + 2)
                if end != -1:
                    content = text[index + 2:end]
                    if _looks_like_inline_math(content):
                        flush_plain()
                        parts.append("\\[" + _convert_math_unicode(content.strip()) + "\\]")
                        index = end + 2
                        continue

            end = _find_closing_dollar(text, index + 1)
            if end != -1:
                content = text[index + 1:end]
                if _looks_like_inline_math(content):
                    flush_plain()
                    parts.append("$" + _convert_math_unicode(content.strip()) + "$")
                    index = end + 1
                    continue

            plain.append("$")
            index += 1
            continue

        plain.append(char)
        index += 1

    flush_plain()
    return "".join(parts)


def _split_page_groups(blocks: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = [[]]
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "page_break":
            groups.append([])
        else:
            groups[-1].append(block)
    return groups


def _paragraph_matches_caption(text: str, description: str) -> bool:
    first_line = text.splitlines()[0].strip().lower()
    return bool(first_line) and first_line in description.lower()


def _figure_dominant_page(blocks: list[dict]) -> dict | None:
    """判断一页是否基本就是一张图：一个 figure + 和图注重叠的短标签。"""
    figures = [block for block in blocks if isinstance(block, dict) and block.get("type") == "figure"]
    if len(figures) != 1:
        return None
    figure = figures[0]
    description = figure.get("description")
    source_image = figure.get("source_image")
    if not isinstance(description, str) or len(description.strip()) < 120:
        return None
    if not isinstance(source_image, str) or not Path(source_image).is_file():
        return None

    others = [block for block in blocks if block is not figure]
    if not others:
        return figure
    if any(not isinstance(block, dict) or block.get("type") != "paragraph" for block in others):
        return None
    labels = []
    for block in others:
        text = block.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 200:
            return None
        labels.append(text)
    matched = sum(1 for text in labels if _paragraph_matches_caption(text, description))
    if matched < max(1, len(labels) - 1):
        return None
    return figure


def _figure_image_tex(block: dict) -> list[str]:
    description = block["description"].strip()
    caption = description.split(". ")[0].strip()[:160] or "原始示意图"
    image_path = Path(block["source_image"]).resolve().as_posix()
    return [
        r"\begin{figure}[htbp]",
        r"\centering",
        r"\includegraphics[width=0.92\linewidth,height=0.78\textheight,keepaspectratio]{\detokenize{"
        + image_path
        + "}}",
        r"\caption{" + _escape_text(caption) + "}",
        r"\end{figure}",
        "",
    ]


def _attach_figure_sources(document: dict, image_path: str) -> None:
    source_image = str(Path(image_path).resolve())
    for block in document.get("blocks", []):
        if isinstance(block, dict) and block.get("type") == "figure":
            block["source_image"] = source_image


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
    for page_index, group in enumerate(_split_page_groups(blocks)):
        if page_index:
            parts.extend([r"\newpage", ""])
        figure_page = _figure_dominant_page(group)
        if figure_page is not None:
            parts.extend(_figure_image_tex(figure_page))
            continue
        for block in group:
            if not isinstance(block, dict):
                raise TypeError("each block must be a dict")
            block_type = block.get("type")
            if block_type == "blank_page":
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


def _usage_signal(completion, max_tokens: int) -> dict:
    """从响应里取出真实的 token 用量与结束原因；取不到就如实留空。"""
    usage = getattr(completion, "usage", None)
    signal = {
        "finish_reason": getattr(completion.choices[0], "finish_reason", None),
        "max_tokens": max_tokens,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
    # 输出预算几乎用满时，内容很可能被截断——这是能核对的事实，不是猜测的分数。
    completion_tokens = signal["completion_tokens"]
    signal["near_token_budget"] = bool(
        isinstance(completion_tokens, int) and max_tokens > 0 and completion_tokens >= max_tokens * 0.95
    )
    return signal


def _call_page_model(image_path: str, max_tokens: int) -> tuple[dict, dict]:
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
    return document, _usage_signal(completion, max_tokens)


def _request_page(image_path: str) -> tuple[dict, dict]:
    """整页识别请求，带一次放宽 token 预算的重试。

    背景：真实多页评估中 page_3 曾因推理 token 耗尽输出预算而返回空内容，
    放宽后重试成功（见 artifacts/multipage_real/report_initial_real.json）。
    只有响应形状问题（空内容 / 截断 / 非 JSON）才重试；配置错误和网络异常
    重试没有意义，直接抛出。
    """
    base_tokens = int(os.environ.get("FULLPAGE_MAX_TOKENS", "24000"))
    budget = base_tokens
    last_error: _PageResponseError | None = None
    attempts = 0
    for attempt in (1, 2):
        attempts = attempt
        try:
            document, signal = _call_page_model(image_path, max_tokens=budget)
            signal["attempts"] = attempts
            signal["retried"] = attempts > 1
            signal["base_max_tokens"] = base_tokens
            return document, signal
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


def _block_stats(blocks) -> dict:
    """统计各类块的数量，用于在界面上如实展示这一页识别出了什么。"""
    stats = {"paragraph": 0, "display_formula": 0, "figure": 0, "blank_page": 0, "other": 0}
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            stats["other"] += 1
            continue
        key = block.get("type")
        if key in stats:
            stats[key] += 1
        else:
            stats["other"] += 1
    return stats


def generate_document(image_path: str) -> dict:
    started = time.perf_counter()
    document, signals = _request_page(image_path)
    _attach_figure_sources(document, image_path)
    tex = build_tex(document)
    return {
        "title": document.get("title") or "手写笔记",
        "blocks": document["blocks"],
        "tex": tex,
        "model": _model_name(),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "human_review": "required",
        "source_image": str(Path(image_path)),
        "signals": {**signals, "block_stats": _block_stats(document.get("blocks"))},
    }
