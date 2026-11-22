import importlib.util
import os
import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import recognizer
import schemas
from reasoner import refine


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PADDLEOCR_AVAILABLE = importlib.util.find_spec("paddleocr") is not None


class BCIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.sample_path = str(_PROJECT_ROOT / "samples" / "sample_plus.png")

    def test_fake_candidate_flows_from_recognizer_to_refine(self):
        with patch(
            "recognizer._run_engine",
            return_value=[schemas.make_candidate("pp_formulanet_l", r"\frac{x^{2}}{2}+1")],
        ):
            candidates = recognizer.recognize(self.sample_path)

        self.assertEqual(len(candidates), 1)
        self.assertTrue(schemas.is_candidate(candidates[0]))
        result = refine(self.sample_path, candidates)
        self.assertEqual(result["raw_latex"], r"\frac{x^{2}}{2}+1")
        self.assertEqual(result["final_latex"], r"\frac{x^{2}}{2}+1")
        self.assertEqual(result["confidence"], "medium")
        self.assertFalse(result["need_review"])

    def test_mock_backend_fails_closed(self):
        with patch.dict(os.environ, {"RECOGNIZER_BACKEND": "mock"}):
            candidates = recognizer.recognize(self.sample_path)

        self.assertEqual(len(candidates), 1)
        self.assertIsNotNone(candidates[0]["error"])
        result = refine(self.sample_path, candidates)
        self.assertEqual(result["raw_latex"], "")
        self.assertEqual(result["confidence"], "low")
        self.assertTrue(result["need_review"])

    def test_b_preserves_outer_whitespace_for_c_trim(self):
        with patch(
            "recognizer._run_engine",
            return_value=[schemas.make_candidate("pp_formulanet_l", " x^2 ")],
        ):
            candidates = recognizer.recognize(self.sample_path)

        result = refine(self.sample_path, candidates)
        self.assertEqual(result["raw_latex"], " x^2 ")
        self.assertEqual(result["final_latex"], "x^2")
        self.assertEqual(result["changes"][0]["rule"], "trim_outer_whitespace")

    def test_same_formula_from_two_engines_is_high_confidence(self):
        with (
            patch("recognizer._enabled_engines", return_value=["engine_a", "engine_b"]),
            patch(
                "recognizer._run_engine",
                side_effect=lambda engine, image_path: [
                    schemas.make_candidate(engine, "x^2")
                ],
            ),
        ):
            candidates = recognizer.recognize(self.sample_path)

        self.assertEqual(len(candidates), 2)
        result = refine(self.sample_path, candidates)
        self.assertEqual(result["confidence"], "high")
        self.assertFalse(result["need_review"])

    def test_same_engine_duplicate_views_are_only_medium_confidence(self):
        @contextmanager
        def duplicate_views(image_path, thorough):
            yield [(image_path, "orig"), (image_path, "zoom")]

        with (
            patch("recognizer._enabled_engines", return_value=["engine_a"]),
            patch("recognizer._iter_views", duplicate_views),
            patch(
                "recognizer._run_engine",
                return_value=[schemas.make_candidate("engine_a", "x^2")],
            ),
        ):
            candidates = recognizer.recognize(self.sample_path, thorough=True)

        self.assertEqual(len(candidates), 1)
        result = refine(self.sample_path, candidates)
        self.assertEqual(result["confidence"], "medium")
        self.assertFalse(result["need_review"])

    def test_b_standalone_contract_suite(self):
        environment = os.environ.copy()
        environment["RECOGNIZER_BACKEND"] = "mock"
        environment["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            [sys.executable, "tests/test_recognizer.py"],
            cwd=_PROJECT_ROOT,
            env=environment,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @unittest.skipUnless(_PADDLEOCR_AVAILABLE, "paddleocr 未安装（requirements-b.txt），跳过")
    def test_default_local_model_directory_is_used(self):
        expected_dir = _PROJECT_ROOT / "models" / "PP-FormulaNet-L"
        with (
            patch.dict(recognizer._MODELS, {}, clear=True),
            patch.dict(
                recognizer.ENGINES["pp_formulanet_l"],
                {"model_name": "PP-FormulaNet-L"},
            ),
            patch.dict(os.environ, {"RECOGNIZER_MODEL_DIR": ""}, clear=False),
            patch("recognizer._device", return_value="cpu"),
            patch("paddleocr.FormulaRecognition") as formula_recognition,
        ):
            recognizer.get_model(recognizer.ENGINE_PP_FORMULANET_L)

        formula_recognition.assert_called_once_with(
            model_name="PP-FormulaNet-L",
            device="cpu",
            model_dir=str(expected_dir),
        )


if __name__ == "__main__":
    unittest.main()
