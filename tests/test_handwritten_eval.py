import json
import tempfile
import unittest
from pathlib import Path

from reasoning.handwritten_eval import evaluate_handwritten, load_manifest


class HandwrittenEvalTests(unittest.TestCase):
    def test_summary_counts_exact_matches(self):
        samples = [
            {"sample_id": "s1", "image_path": "data/handwritten/sample_1.png", "ground_truth": "x^{2}"},
            {"sample_id": "s2", "image_path": "data/handwritten/sample_2.png", "ground_truth": "y"},
        ]

        def recognize_fn(path):
            return [
                {
                    "engine": "fake",
                    "latex": "x^{2}",
                    "score": None,
                    "latency_ms": 12.5,
                    "error": None,
                }
            ]

        def refine_fn(path, candidates):
            return {
                "raw_latex": candidates[0]["latex"],
                "final_latex": candidates[0]["latex"],
                "confidence": "medium",
                "changes": [],
                "need_review": False,
                "risk_score": None,
            }

        report = evaluate_handwritten(
            samples,
            recognize_fn=recognize_fn,
            refine_fn=refine_fn,
        )

        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["summary"]["raw_correct_count"], 1)
        self.assertEqual(report["summary"]["final_correct_count"], 1)
        self.assertEqual(report["summary"]["final_exact_accuracy"], 0.5)
        self.assertTrue(report["results"][0]["final_correct"])
        self.assertFalse(report["results"][1]["final_correct"])

    def test_recognizer_exception_is_recorded_and_does_not_abort(self):
        samples = [
            {"sample_id": "s1", "image_path": "data/handwritten/sample_1.png", "ground_truth": "x"},
        ]

        def recognize_fn(path):
            raise RuntimeError("model exploded")

        def refine_fn(path, candidates):
            raise AssertionError("refine must not run when recognition failed")

        report = evaluate_handwritten(
            samples,
            recognize_fn=recognize_fn,
            refine_fn=refine_fn,
        )

        record = report["results"][0]
        self.assertIn("model exploded", record["error"])
        self.assertFalse(record["final_correct"])
        self.assertTrue(record["need_review"])
        self.assertEqual(report["summary"]["final_exact_accuracy"], 0.0)

    def test_repository_manifest_has_12_confirmed_samples(self):
        manifest = load_manifest()
        self.assertEqual(manifest["review_status"], "ground_truth_user_confirmed")
        self.assertEqual(manifest["sample_count"], 12)
        self.assertEqual(len(manifest["samples"]), 12)
        root = Path(__file__).resolve().parent.parent
        for sample in manifest["samples"]:
            self.assertTrue((root / sample["image_path"]).is_file(), sample["image_path"])

    def test_thorough_flag_is_forwarded(self):
        samples = [
            {"sample_id": "s1", "image_path": "data/handwritten/sample_1.png", "ground_truth": "x"},
        ]
        seen = {}

        def recognize_fn(path, thorough=False):
            seen["thorough"] = thorough
            return []

        def refine_fn(path, candidates):
            return {
                "raw_latex": "",
                "final_latex": "",
                "confidence": "low",
                "changes": [],
                "need_review": True,
                "risk_score": None,
            }

        evaluate_handwritten(
            samples,
            recognize_fn=recognize_fn,
            refine_fn=refine_fn,
            thorough=True,
        )

        self.assertTrue(seen["thorough"])

    def test_manifest_rejects_missing_ground_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(
                json.dumps({"samples": [{"sample_id": "s1", "image_path": "a.png"}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_manifest(path)


if __name__ == "__main__":
    unittest.main()