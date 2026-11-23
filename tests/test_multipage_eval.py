import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench.multipage_eval import run_evaluation


class MultipageEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "output"

    def tearDown(self):
        self.temporary.cleanup()

    def _manifest(self, pages, cases):
        for page in pages.values():
            image = self.root / f"{Path(page['image']).stem}.png"
            image.write_bytes(page["image"].encode("utf-8"))
            page["image"] = str(image)
        manifest = {
            "sample_type": "test_multipage",
            "evaluation_scope": "structure only",
            "transcription_accuracy": "not_evaluated",
            "pages": pages,
            "cases": cases,
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return path

    def _compile(self, tex_path):
        tex_path = Path(tex_path)
        pdf_path = tex_path.with_suffix(".pdf")
        pdf_path.write_bytes(b"%PDF-test")
        return {
            "success": True,
            "pdf_path": str(pdf_path),
            "log": "compiled",
            "errors": [],
            "returncode": 0,
        }

    def _pdf_pages(self, pdf_path):
        tex = pdf_path.with_suffix(".tex").read_text(encoding="utf-8")
        return tex.count(r"\newpage") + 1

    @patch("workbench.multipage_eval._pdf_page_count")
    @patch("workbench.multipage_eval.compile_tex")
    @patch("workbench.multipage_eval._request_page")
    def test_shared_page_responses_are_reused_and_order_is_checked(self, request, compile_mock, pdf_pages):
        pages = {
            "one": {"image": "one.png", "marker": "甲"},
            "two": {"image": "two.png", "marker": "乙"},
            "three": {"image": "three.png", "marker": "丙"},
        }
        cases = [
            {"id": "forward", "page_ids": ["one", "two", "three"]},
            {"id": "reverse", "page_ids": ["three", "one"]},
        ]
        manifest = self._manifest(pages, cases)
        documents = {
            "one.png": {"title": "一", "blocks": [{"type": "paragraph", "text": "甲"}]},
            "two.png": {"title": "二", "blocks": [{"type": "paragraph", "text": "乙"}]},
            "three.png": {"title": "三", "blocks": [{"type": "paragraph", "text": "丙"}]},
        }
        request.side_effect = lambda image: (documents[Path(image).name], {"attempts": 1})
        compile_mock.side_effect = self._compile
        pdf_pages.side_effect = self._pdf_pages

        report = run_evaluation(manifest, self.output)

        self.assertEqual(request.call_count, 3)
        self.assertEqual(report["additional_api_calls"], 3)
        self.assertEqual(report["cache_hits"], 2)
        self.assertEqual(report["cases_structurally_passed"], 2)
        reverse_tex = (self.output / "reverse" / "main.tex").read_text(encoding="utf-8")
        self.assertLess(reverse_tex.index("丙"), reverse_tex.index("甲"))
        self.assertEqual(reverse_tex.count(r"\newpage"), 1)

        offline_report = run_evaluation(manifest, self.output, offline=True)

        self.assertEqual(request.call_count, 3)
        self.assertEqual(offline_report["additional_api_calls"], 0)
        self.assertEqual(offline_report["cache_hits"], 5)
        self.assertEqual(offline_report["cases_structurally_passed"], 2)

    @patch("workbench.multipage_eval._pdf_last_page_is_blank")
    @patch("workbench.multipage_eval._pdf_page_count")
    @patch("workbench.multipage_eval.compile_tex")
    @patch("workbench.multipage_eval._request_page")
    def test_empty_page_response_is_normalized_cached_and_compiled(
        self, request, compile_mock, pdf_pages, pdf_blank
    ):
        pages = {
            "content": {"image": "content.png", "marker": "甲"},
            "blank": {"image": "blank.png", "expected_blank": True},
        }
        manifest = self._manifest(pages, [{"id": "blank_case", "page_ids": ["content", "blank"]}])
        request.side_effect = [
            ({"title": "内容", "blocks": [{"type": "paragraph", "text": "甲"}]}, {"attempts": 1}),
            ({"title": "空白", "blocks": []}, {"attempts": 1}),
        ]
        compile_mock.side_effect = self._compile
        pdf_pages.side_effect = self._pdf_pages
        pdf_blank.return_value = True

        report = run_evaluation(manifest, self.output)

        result = report["results"][0]
        self.assertEqual(result["status"], "compiled")
        self.assertTrue(result["structural_pass"])
        self.assertEqual(result["pages"][1]["status"], "success")
        self.assertTrue(result["pages"][1]["normalized_empty_blank"])
        self.assertFalse(result["pages"][1]["blank_page_has_content"])
        compile_mock.assert_called_once()
        cached = json.loads((self.output / "cache" / "pages" / "blank.json").read_text(encoding="utf-8"))
        self.assertEqual(cached["raw_document"]["blocks"], [])
        self.assertEqual(cached["document"]["blocks"], [{"type": "blank_page"}])

        offline_report = run_evaluation(manifest, self.output, offline=True)

        self.assertEqual(request.call_count, 2)
        self.assertEqual(offline_report["additional_api_calls"], 0)
        self.assertEqual(offline_report["successful_cache_hits"], 2)
        self.assertTrue(offline_report["results"][0]["structural_pass"])

    @patch("workbench.multipage_eval._pdf_last_page_is_blank")
    @patch("workbench.multipage_eval._pdf_page_count")
    @patch("workbench.multipage_eval.compile_tex")
    @patch("workbench.multipage_eval._request_page")
    def test_invented_content_on_blank_page_fails_structural_check(
        self, request, compile_mock, pdf_pages, pdf_blank
    ):
        pages = {
            "content": {"image": "content.png", "marker": "甲"},
            "blank": {"image": "blank.png", "expected_blank": True},
        }
        manifest = self._manifest(pages, [{"id": "blank_case", "page_ids": ["content", "blank"]}])
        request.side_effect = [
            ({"title": "内容", "blocks": [{"type": "paragraph", "text": "甲"}]}, {"attempts": 1}),
            ({"title": "空白", "blocks": [{"type": "paragraph", "text": "这是一张空白页"}]}, {"attempts": 1}),
        ]
        compile_mock.side_effect = self._compile
        pdf_pages.side_effect = self._pdf_pages
        pdf_blank.return_value = False

        report = run_evaluation(manifest, self.output)

        result = report["results"][0]
        self.assertEqual(result["status"], "compiled")
        self.assertFalse(result["structural_pass"])
        self.assertFalse(result["blank_pages_faithful"])
        self.assertTrue(result["pages"][1]["blank_page_has_content"])


if __name__ == "__main__":
    unittest.main()
