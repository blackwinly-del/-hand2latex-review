import json
import tempfile
import unittest
from pathlib import Path

from workbench.full_page_eval import (
    GroundTruthNotConfirmed,
    compare_page,
    confirmation_state,
    evaluate_full_pages,
    load_ground_truth,
)


def _manifest(status="user_confirmed", pages=None, uncertainty=None):
    return {
        "review_status": status,
        "pages": pages or [
            {
                "page_id": "p1",
                "image_path": "x.png",
                "human_review": "confirmed",
                "lines": ["a+b", "c=d"],
                "uncertainty": uncertainty or [],
                "expected_blank": False,
            }
        ],
    }


class ConfirmationGateTests(unittest.TestCase):
    def test_unconfirmed_ground_truth_refuses_to_score(self):
        """未确认的真值不能算准确率——这是这个模块存在的理由。

        草稿是模型读图写的，它会和自己的转录犯同样的错。两边一起错时
        准确率显示 100%，比没有指标更危险。
        """
        manifest = _manifest(status="machine_drafted_pending_human_confirmation")
        with self.assertRaises(GroundTruthNotConfirmed) as ctx:
            evaluate_full_pages(manifest, {"p1": "a+b\nc=d"})
        self.assertIn("人工确认", str(ctx.exception))

    def test_partially_confirmed_pages_still_block(self):
        """每页的 human_review 没确认，整体状态写 confirmed 也不算数。"""
        pages = [
            {"page_id": "p1", "image_path": "x.png", "human_review": "confirmed", "lines": ["a"]},
            {"page_id": "p2", "image_path": "y.png", "human_review": "pending", "lines": ["b"]},
        ]
        state = confirmation_state(_manifest(pages=pages))
        self.assertIn("p2", state["pending_pages"])

    def test_missing_status_counts_as_unconfirmed(self):
        manifest = _manifest()
        del manifest["review_status"]
        self.assertFalse(confirmation_state(manifest)["confirmed"])

    def test_allow_unconfirmed_marks_report_as_unusable(self):
        manifest = _manifest(status="machine_drafted_pending_human_confirmation")
        report = evaluate_full_pages(manifest, {"p1": "a+b\nc=d"}, allow_unconfirmed=True)
        self.assertIn("WARNING", report)
        self.assertIn("不可对外引用", report["WARNING"])


class ComparePageTests(unittest.TestCase):
    def test_exact_match(self):
        result = compare_page(["a+b", "c=d"], "a+b\nc=d")
        self.assertTrue(result["exact_page_match"])
        self.assertEqual(result["line_accuracy"], 1.0)

    def test_whitespace_differences_are_not_errors(self):
        """缩进和多余空格不该算错——它们不是转录内容。"""
        result = compare_page(["a+b", "c=d"], "  a+b  \n\nc=d   ")
        self.assertTrue(result["exact_page_match"])

    def test_missing_line_is_located(self):
        result = compare_page(["a", "b", "c"], "a\nc")
        self.assertFalse(result["exact_page_match"])
        self.assertEqual([item["text"] for item in result["missing"]], ["b"])

    def test_insertion_does_not_shift_all_following_lines(self):
        """多出一行时，后面正确的行不能被算成全错。

        按行号硬比会让插入点之后的所有行错位，差异报告就没法看了。
        """
        result = compare_page(["a", "b", "c"], "a\nX\nb\nc")
        self.assertEqual(result["missing"], [])
        self.assertEqual([item["text"] for item in result["extra"]], ["X"])
        self.assertEqual(result["matched_lines"], 3)

    def test_blank_page_with_invented_content_is_flagged(self):
        """在空白页上编内容是整页识别最典型的失败，必须单独标出来。"""
        pages = [
            {
                "page_id": "blank",
                "image_path": "z.png",
                "human_review": "confirmed",
                "lines": [],
                "expected_blank": True,
            }
        ]
        report = evaluate_full_pages(_manifest(pages=pages), {"blank": "编出来的公式"})
        self.assertEqual(report["invented_content_pages"], ["blank"])

    def test_empty_blank_page_is_correct(self):
        pages = [
            {
                "page_id": "blank",
                "image_path": "z.png",
                "human_review": "confirmed",
                "lines": [],
                "expected_blank": True,
            }
        ]
        report = evaluate_full_pages(_manifest(pages=pages), {"blank": ""})
        self.assertEqual(report["invented_content_pages"], [])
        self.assertTrue(report["pages"][0]["exact_page_match"])

    def test_page_without_transcription_is_not_scored(self):
        report = evaluate_full_pages(_manifest(), {})
        self.assertEqual(report["evaluated_pages"], 0)
        self.assertFalse(report["pages"][0]["evaluated"])


class LoadGroundTruthTests(unittest.TestCase):
    def test_rejects_missing_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.json"
            path.write_text(json.dumps({"review_status": "user_confirmed", "pages": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_ground_truth(path)

    def test_rejects_entry_without_image_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.json"
            path.write_text(
                json.dumps({"pages": [{"page_id": "p1", "lines": ["a"]}]}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_ground_truth(path)

    def test_real_manifest_is_loadable(self):
        manifest = load_ground_truth()
        self.assertTrue(manifest["pages"])
        ids = [page["page_id"] for page in manifest["pages"]]
        self.assertIn("page_2", ids)

    def test_real_manifest_is_currently_unconfirmed(self):
        """这一条是如实的状态记录：草稿仍在等人工核对。

        等真被确认之后这条测试应该改成断言 confirmed——它红了就说明
        该去更新 README 里"整页无真值"的说法了，不是改测试迁就现状。
        """
        state = confirmation_state(load_ground_truth())
        self.assertFalse(state["confirmed"])
        self.assertEqual(state["review_status"], "machine_drafted_pending_human_confirmation")


if __name__ == "__main__":
    unittest.main()
