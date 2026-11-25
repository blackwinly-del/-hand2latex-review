import json
import os

from workbench.full_page import _client, _ctex_fontset, _model_name


def suggest_fix(tex: str, compile_log: str) -> dict:
    if not tex.strip():
        raise ValueError("tex must not be blank")
    if not compile_log.strip():
        raise ValueError("compile log must not be blank")

    client = _client()
    completion = client.chat.completions.create(
        model=_model_name(),
        messages=[
            {
                "role": "system",
                "content": (
                    "Repair a LaTeX document using its source and Tectonic log. Return only JSON "
                    "with fixed_tex and summary strings. Fix only the reported compilation errors "
                    "and preserve every unrelated Chinese sentence, formula, and document block. "
                    "Do not improve, solve, normalize, or rewrite the transcription. Keep a "
                    "ctex-compatible preamble with fontset=" + _ctex_fontset() + "."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Current .tex:\n" + tex + "\n\nTectonic log:\n" + compile_log
                ),
            },
        ],
        max_tokens=int(os.environ.get("FULLPAGE_MAX_TOKENS", "24000")),
        response_format={"type": "json_object"},
    )
    content = completion.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("fix response content is empty")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise TypeError("fix response must be a JSON object")
    if not isinstance(result.get("fixed_tex"), str) or not result["fixed_tex"].strip():
        raise ValueError("fixed_tex must not be blank")
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        raise ValueError("fix summary must not be blank")
    return result
