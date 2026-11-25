import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf

from workbench.compiler import _find_tectonic, compile_tex, parse_compile_errors
from workbench.full_page import (
    _PageResponseError,
    _call_page_model,
    _ctex_documentclass,
    _ctex_fontset,
    _escape_text,
    _request_page,
    build_tex,
    generate_document,
    merge_documents,
)
from workbench.multipage_eval import _pdf_last_page_is_blank


class FontsetConfigTests(unittest.TestCase):
    def test_default_fontset_is_windows(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_ctex_fontset(), "windows")
            self.assertEqual(
                _ctex_documentclass(),
                r"\documentclass[UTF8,fontset=windows]{ctexart}",
            )

    def test_fontset_can_be_overridden(self):
        with patch.dict(os.environ, {"LATEX_FONTSET": "FANDOL"}):
            self.assertEqual(_ctex_fontset(), "fandol")
            self.assertIn("fontset=fandol", _ctex_documentclass())
            self.assertIn("fontset=fandol", build_tex({
                "title": "笔记",
                "blocks": [{"type": "paragraph", "text": "内容"}],
            }))

    def test_invalid_fontset_is_rejected(self):
        with patch.dict(os.environ, {"LATEX_FONTSET": "not-a-fontset"}):
            with self.assertRaises(RuntimeError):
                _ctex_fontset()


class FullPageDocumentTests(unittest.TestCase):
    def test_build_tex_preserves_formula_and_escapes_plain_text(self):
        document = {
            "title": "测试_笔记",
            "blocks": [
                {"type": "paragraph", "text": "占比50%_保留"},
                {"type": "display_formula", "latex": r"\frac{x}{0}"},
            ],
        }

        tex = build_tex(document)

        self.assertIn("ctexart", tex)
        self.assertIn(r"测试\_笔记", tex)
        self.assertIn(r"50\%\_保留", tex)
        self.assertIn("\\[\n\\frac{x}{0}\n\\]", tex)

    def test_escape_text_preserves_paired_inline_math(self):
        self.assertEqual(
            _escape_text(r"若 $x^2$ 且 $\frac{1}{2}$ 成立"),
            r"若 $x^2$ 且 $\frac{1}{2}$ 成立",
        )

    def test_escape_text_escapes_unmatched_dollars(self):
        self.assertEqual(_escape_text(r"价格 $5 与 \$10"), r"价格 \$5 与 \$10")

    def test_escape_text_does_not_treat_chinese_pair_as_math(self):
        self.assertEqual(_escape_text("甲 $ 中 乙 $ 丙"), r"甲 \$ 中 乙 \$ 丙")

    def test_escape_text_converts_unicode_math_in_prose(self):
        self.assertEqual(
            _escape_text("若 x ∈ A 且 x ≤ 3"),
            r"若 x $\in$ A 且 x $\le$ 3",
        )

    def test_escape_text_converts_unicode_math_inside_math(self):
        self.assertEqual(_escape_text("$x∈A$"), r"$x\in A$")

    def test_escape_text_keeps_display_math(self):
        self.assertEqual(_escape_text("$$x∈A$$"), r"\[x\in A\]")

    def test_build_tex_embeds_source_image_for_figure_dominant_page(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"image")
            description = (
                "A flowchart illustrating a psychological model. It shows Social Feedback "
                "and Memory with arrows, plus a legend for causal and feedback paths."
            )
            tex = build_tex({
                "title": "图页",
                "blocks": [
                    {"type": "figure", "description": description, "source_image": str(image_path)},
                    {"type": "paragraph", "text": "Social Feedback\n(e.g., acceptance)"},
                    {"type": "paragraph", "text": "Memory\n(e.g., social events)"},
                ],
            })

            self.assertIn(r"\includegraphics", tex)
            self.assertIn(r"\detokenize{", tex)
            self.assertNotIn("原始示意图（未重新绘制）", tex)
            self.assertNotIn("Social Feedback\n(e.g., acceptance)", tex)

    def test_build_tex_keeps_description_for_mixed_figure_page(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"image")
            tex = build_tex({
                "title": "图文混排",
                "blocks": [
                    {
                        "type": "figure",
                        "description": "A flowchart of a psychological model with Social Feedback and Memory.",
                        "source_image": str(image_path),
                    },
                    {"type": "paragraph", "text": "这是一段不在图注里的正文，需要保留。"},
                ],
            })

            self.assertIn("原始示意图（未重新绘制）", tex)
            self.assertIn("这是一段不在图注里的正文，需要保留。", tex)
            self.assertNotIn(r"\includegraphics", tex)

    def test_generate_document_attaches_figure_source_image(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"image")
            document = {
                "title": "图页",
                "blocks": [
                    {
                        "type": "figure",
                        "description": (
                            "A flowchart illustrating a psychological model with several boxes, "
                            "arrows, feedback loops, and a legend explaining each relationship."
                        ),
                    }
                ],
            }
            with patch("workbench.full_page._request_page", return_value=(document, {"attempts": 1})):
                result = generate_document(str(image_path))

            self.assertEqual(result["blocks"][0]["source_image"], str(image_path.resolve()))
            self.assertIn(r"\includegraphics", result["tex"])

    def test_build_tex_keeps_inline_math_in_paragraph(self):
        tex = build_tex({
            "title": "行内公式",
            "blocks": [{"type": "paragraph", "text": r"若 $x∈A$ 则成立"}],
        })

        self.assertIn(r"若 $x\in A$ 则成立", tex)
        self.assertNotIn(r"\$x", tex)

    def test_empty_blocks_are_rejected(self):
        with self.assertRaises(ValueError):
            build_tex({"title": "empty", "blocks": []})

    def test_merge_documents_inserts_real_page_breaks(self):
        merged = merge_documents([
            {"title": "第一页", "blocks": [{"type": "paragraph", "text": "甲"}]},
            {"title": "第二页", "blocks": [{"type": "display_formula", "latex": "x^2"}]},
            {"title": "第三页", "blocks": [{"type": "paragraph", "text": "乙"}]},
        ])

        tex = build_tex(merged)

        self.assertEqual(merged["title"], "第一页")
        self.assertEqual(tex.count(r"\newpage"), 2)
        self.assertLess(tex.index("甲"), tex.index("x^2"))
        self.assertLess(tex.index("x^2"), tex.index("乙"))
        with self.assertRaises(ValueError):
            merge_documents([])

    @patch("workbench.full_page._request_page")
    def test_generate_document_returns_editable_tex_and_review_status(self, request_mock):
        request_mock.return_value = (
            {
                "title": "手写笔记",
                "blocks": [{"type": "display_formula", "latex": "x^2"}],
            },
            {"attempts": 1, "retried": False, "finish_reason": "stop", "completion_tokens": 12},
        )

        result = generate_document("unused.png")

        self.assertIn("x^2", result["tex"])
        self.assertEqual(result["human_review"], "required")
        self.assertGreaterEqual(result["latency_ms"], 0)
        self.assertEqual(result["signals"]["finish_reason"], "stop")
        self.assertFalse(result["signals"]["retried"])
        self.assertEqual(result["signals"]["block_stats"]["display_formula"], 1)

    def test_near_token_budget_flag_uses_real_usage(self):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}"))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=950, total_tokens=1050),
        )
        with patch("workbench.full_page._client") as client_mock:
            client_mock.return_value.chat.completions.create.return_value = completion
            with patch("workbench.full_page._read_image_data_url", return_value="data:,"):
                _, signal = _call_page_model("unused.png", max_tokens=1000)

        self.assertEqual(signal["completion_tokens"], 950)
        self.assertTrue(signal["near_token_budget"])
        self.assertEqual(signal["finish_reason"], "stop")

    def test_missing_usage_is_reported_as_unknown_not_invented(self):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}"))],
            usage=None,
        )
        with patch("workbench.full_page._client") as client_mock:
            client_mock.return_value.chat.completions.create.return_value = completion
            with patch("workbench.full_page._read_image_data_url", return_value="data:,"):
                _, signal = _call_page_model("unused.png", max_tokens=1000)

        self.assertIsNone(signal["completion_tokens"])
        self.assertFalse(signal["near_token_budget"])


class PageRequestRetryTests(unittest.TestCase):
    """整页识别的"放宽 token 预算重试一次"行为（对应真实评估中 page_3 的失败案例）。"""

    @patch("workbench.full_page._call_page_model")
    def test_transient_response_error_is_retried_with_relaxed_budget(self, call_mock):
        call_mock.side_effect = [
            _PageResponseError("full-page response content is empty (finish_reason=None)"),
            ({"title": "手写笔记", "blocks": [{"type": "paragraph", "text": "甲"}]}, {"finish_reason": "stop"}),
        ]

        result, signals = _request_page("unused.png")

        self.assertEqual(result["title"], "手写笔记")
        self.assertTrue(signals["retried"])
        self.assertEqual(signals["attempts"], 2)
        self.assertEqual(signals["finish_reason"], "stop")
        self.assertEqual(call_mock.call_count, 2)
        base = int(os.environ.get("FULLPAGE_MAX_TOKENS", "24000"))
        self.assertEqual(call_mock.call_args_list[0].kwargs["max_tokens"], base)
        self.assertEqual(call_mock.call_args_list[1].kwargs["max_tokens"], int(base * 1.5))

    @patch("workbench.full_page._call_page_model")
    def test_first_attempt_success_is_not_marked_retried(self, call_mock):
        call_mock.return_value = (
            {"title": "手写笔记", "blocks": [{"type": "paragraph", "text": "甲"}]},
            {"finish_reason": "stop"},
        )

        _, signals = _request_page("unused.png")

        self.assertFalse(signals["retried"])
        self.assertEqual(signals["attempts"], 1)
        self.assertEqual(call_mock.call_count, 1)

    @patch("workbench.full_page._call_page_model")
    def test_second_failure_propagates_after_retry(self, call_mock):
        call_mock.side_effect = [
            _PageResponseError("empty"),
            _PageResponseError("still empty"),
        ]

        with self.assertRaises(_PageResponseError):
            _request_page("unused.png")

        self.assertEqual(call_mock.call_count, 2)

    @patch("workbench.full_page._call_page_model")
    def test_non_transient_error_is_not_retried(self, call_mock):
        call_mock.side_effect = RuntimeError("OPENAI_API_KEY is not configured")

        with self.assertRaises(RuntimeError):
            _request_page("unused.png")

        self.assertEqual(call_mock.call_count, 1)


class TectonicCompilerTests(unittest.TestCase):
    def test_compile_chinese_document(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = Path(directory) / "main.tex"
            tex_path.write_text(
                _ctex_documentclass() + "\n"
                "\\begin{document}\n"
                "你好，Tectonic！$x^2$\n"
                "\\end{document}\n",
                encoding="utf-8",
            )

            result = compile_tex(tex_path)

            self.assertTrue(result["success"], result["log"])
            self.assertTrue(Path(result["pdf_path"]).is_file())

    def test_compile_paragraph_with_inline_math_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = Path(directory) / "main.tex"
            tex = build_tex({
                "title": "含 ∈ 的笔记",
                "blocks": [{"type": "paragraph", "text": "若 $x∈A$ 且 x ≤ 3，则 $x^2$ 成立"}],
            })

            self.assertNotIn(r"\$", tex)
            tex_path.write_text(tex, encoding="utf-8")
            result = compile_tex(tex_path)

            self.assertTrue(result["success"], result["log"])
            self.assertNotIn("Missing character", result["log"])

    def test_compile_figure_dominant_page_with_source_image(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = Path(directory) / "main.tex"
            source = (Path(__file__).resolve().parent.parent / "samples" / "sample_plus.png").resolve()
            tex = build_tex({
                "title": "图形页",
                "blocks": [
                    {
                        "type": "figure",
                        "description": (
                            "A handwritten formula image used as a figure. It contains a polynomial "
                            "expression and should be embedded as the original image."
                        ),
                        "source_image": str(source),
                    }
                ],
            })
            tex_path.write_text(tex, encoding="utf-8")

            result = compile_tex(tex_path)

            self.assertTrue(result["success"], result["log"])
            with pymupdf.open(result["pdf_path"]) as document:
                self.assertEqual(document.page_count, 1)
                self.assertTrue(document[0].get_images())

    def test_compile_trailing_blank_page(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = Path(directory) / "main.tex"
            merged = merge_documents([
                {"title": "笔记", "blocks": [{"type": "paragraph", "text": "第一页"}]},
                {"title": "空白", "blocks": [{"type": "blank_page"}]},
            ])
            tex_path.write_text(build_tex(merged), encoding="utf-8")

            result = compile_tex(tex_path)

            self.assertTrue(result["success"], result["log"])
            with pymupdf.open(result["pdf_path"]) as document:
                self.assertEqual(document.page_count, 2)
                last_page = document[-1]
                self.assertIn(last_page.get_text().strip(), ("", "2"))
                self.assertFalse(last_page.get_images())
                self.assertFalse(last_page.get_drawings())
            self.assertTrue(_pdf_last_page_is_blank(Path(result["pdf_path"])))

    def test_compile_error_is_reported_with_source_line(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = Path(directory) / "main.tex"
            tex_path.write_text(
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "第一行\n"
                "\\badmacro\n"
                "\\end{document}\n",
                encoding="utf-8",
            )
            tex_path.with_suffix(".pdf").write_bytes(b"%PDF-old")

            result = compile_tex(tex_path)

            self.assertFalse(result["success"])
            self.assertTrue(result["errors"], result["log"])
            self.assertEqual(result["errors"][0]["line"], 4)
            self.assertFalse(tex_path.with_suffix(".pdf").exists())

    @patch("workbench.compiler._find_tectonic", return_value=None)
    def test_missing_compiler_does_not_leave_stale_pdf(self, _locator):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = Path(directory) / "main.tex"
            tex_path.write_text("content", encoding="utf-8")
            tex_path.with_suffix(".pdf").write_bytes(b"%PDF-old")

            with self.assertRaises(RuntimeError):
                compile_tex(tex_path)

            self.assertFalse(tex_path.with_suffix(".pdf").exists())

    def test_parse_compile_error_formats(self):
        log = "main.tex:7: Undefined control sequence\nerror: at line 9: missing brace"
        self.assertEqual(parse_compile_errors(log)[0], {"line": 7, "message": "Undefined control sequence"})


class TectonicLocatorTests(unittest.TestCase):
    def test_builtin_binary_is_found_with_platform_name(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / ("tectonic.exe" if os.name == "nt" else "tectonic")
            binary.write_bytes(b"fake-binary")
            with patch("workbench.compiler._TECTONIC_DIR", Path(directory)):
                self.assertEqual(_find_tectonic(), binary)

    def test_fallback_name_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            # 从另一个平台拷来的目录：只有"另一种命名"的二进制，也应能找到
            binary = Path(directory) / ("tectonic" if os.name == "nt" else "tectonic.exe")
            binary.write_bytes(b"fake-binary")
            with patch("workbench.compiler._TECTONIC_DIR", Path(directory)):
                self.assertEqual(_find_tectonic(), binary)

    def test_missing_binary_reports_install_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = Path(directory) / "main.tex"
            tex_path.write_text("content", encoding="utf-8")
            with (
                patch("workbench.compiler._TECTONIC_DIR", Path(directory) / "tools" / "tectonic"),
                patch("workbench.compiler.shutil.which", return_value=None),
                self.assertRaisesRegex(RuntimeError, "tectonic is not installed"),
            ):
                compile_tex(tex_path)


if __name__ == "__main__":
    unittest.main()
