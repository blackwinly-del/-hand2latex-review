import json
import os
import time
from pathlib import Path

from openai import OpenAI

from reasoning.context import _read_image_data_url


def _client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    if not api_key or not api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not model or not model.strip():
        raise RuntimeError("OPENAI_MODEL is not configured")
    return OpenAI(
        api_key=api_key.strip(),
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        timeout=float(os.environ.get("FULLPAGE_TIMEOUT_SECONDS", "120")),
    )


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
        r"\documentclass[UTF8,fontset=windows]{ctexart}",
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


def _request_page(image_path: str) -> dict:
    client = _client()
    completion = client.chat.completions.create(
        model=os.environ["OPENAI_MODEL"].strip(),
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
        max_tokens=int(os.environ.get("FULLPAGE_MAX_TOKENS", "24000")),
        response_format={"type": "json_object"},
    )
    choice = completion.choices[0]
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"full-page response content is empty (finish_reason={choice.finish_reason})")
    if choice.finish_reason == "length":
        raise ValueError("full-page response was truncated by max_tokens")
    try:
        document = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"full-page response was not valid JSON "
            f"(finish_reason={choice.finish_reason}, length={len(content)})"
        ) from error
    if not isinstance(document, dict):
        raise TypeError("full-page response must be a JSON object")
    return document


def generate_document(image_path: str) -> dict:
    started = time.perf_counter()
    document = _request_page(image_path)
    tex = build_tex(document)
    return {
        "title": document.get("title") or "手写笔记",
        "blocks": document["blocks"],
        "tex": tex,
        "model": os.environ["OPENAI_MODEL"].strip(),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "human_review": "required",
        "source_image": str(Path(image_path)),
    }
