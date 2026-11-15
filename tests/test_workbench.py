import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from workbench.compiler import compile_tex, parse_compile_errors
from workbench.full_page import build_tex, generate_document, merge_documents
from workbench.multipage_eval import _pdf_last_page_is_blank


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
        request_mock.return_value = {
            "title": "手写笔记",
            "blocks": [{"type": "display_formula", "latex": "x^2"}],
        }

        result = generate_document("unused.png")

        self.assertIn("x^2", result["tex"])
        self.assertEqual(result["human_review"], "required")
        self.assertGreaterEqual(result["latency_ms"], 0)


class TectonicCompilerTests(unittest.TestCase):
    def test_compile_chinese_document(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = Path(directory) / "main.tex"
            tex_path.write_text(
                "\\documentclass[UTF8,fontset=windows]{ctexart}\n"
                "\\begin{document}\n"
                "你好，Tectonic！$x^2$\n"
                "\\end{document}\n",
                encoding="utf-8",
            )

            result = compile_tex(tex_path)

            self.assertTrue(result["success"], result["log"])
            self.assertTrue(Path(result["pdf_path"]).is_file())

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

    @patch("workbench.compiler._TECTONIC", Path("missing-tectonic.exe"))
    def test_missing_compiler_does_not_leave_stale_pdf(self):
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


if __name__ == "__main__":
    unittest.main()
