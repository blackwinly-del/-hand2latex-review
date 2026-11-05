import base64
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import reasoning.context as context_module
from reasoner import refine
from reasoning.context import _read_image_data_url, _request_context, choose_with_context


class ContextSelectionTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"engine": "a", "latex": "x", "error": None},
            {"engine": "b", "latex": "y", "error": None},
        ]

    @patch("reasoning.context._request_context")
    def test_mock_context_selects_existing_candidate(self, request_mock):
        request_mock.return_value = {"selected_index": 1, "reason": "matches image"}
        original = copy.deepcopy(self.candidates)

        result = choose_with_context("image.png", self.candidates)

        self.assertEqual(
            result,
            {"selected_index": 1, "reason": "matches image", "error": None},
        )
        request_mock.assert_called_once_with("image.png", self.candidates)
        self.assertEqual(self.candidates, original)

    @patch("reasoning.context._request_context")
    def test_api_failure_returns_error_instead_of_guessing(self, request_mock):
        request_mock.side_effect = ConnectionError("offline")

        result = choose_with_context("image.png", self.candidates)

        self.assertIsNone(result["selected_index"])
        self.assertEqual(result["reason"], "")
        self.assertIn("ConnectionError", result["error"])

    @patch("reasoning.context._request_context")
    def test_api_error_details_are_not_exposed(self, request_mock):
        request_mock.side_effect = ConnectionError("secret-key and internal response")

        result = choose_with_context("image.png", self.candidates)

        self.assertEqual(result["error"], "ConnectionError: context selection failed")
        self.assertNotIn("secret-key", result["error"])
        self.assertNotIn("internal response", result["error"])

    @patch("reasoning.context._request_context")
    def test_invalid_context_responses_require_review(self, request_mock):
        invalid_responses = [
            None,
            {},
            {"selected_index": 2, "reason": "out of range"},
            {"selected_index": -1, "reason": "negative index"},
            {"selected_index": 1.0, "reason": "not an integer"},
            {"selected_index": "1", "reason": "not an integer"},
            {"selected_index": True, "reason": "not an integer"},
            {"selected_index": 0, "reason": " "},
        ]
        for response in invalid_responses:
            with self.subTest(response=response):
                request_mock.return_value = response
                result = choose_with_context("image.png", self.candidates)
                self.assertIsNone(result["selected_index"])
                self.assertTrue(result["error"])

    @patch("reasoning.context._request_context")
    def test_invalid_inputs_are_rejected_before_context_call(self, request_mock):
        invalid_cases = [
            ("", self.candidates, ValueError),
            (None, self.candidates, TypeError),
            ("image.png", self.candidates[:1], ValueError),
            ("image.png", [self.candidates[0], {"latex": "y", "error": "failed"}], ValueError),
        ]
        for image_path, candidates, error_type in invalid_cases:
            with self.subTest(image_path=image_path, candidates=candidates):
                with self.assertRaises(error_type):
                    choose_with_context(image_path, candidates)
        request_mock.assert_not_called()


class OpenAIContextRequestTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"engine": "a", "latex": "x", "error": None},
            {"engine": "b", "latex": "y", "error": None},
        ]
        self.environment = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "https://api.example.test/v1",
            "OPENAI_MODEL": "vision-model",
            "OPENAI_TIMEOUT_SECONDS": "12.5",
        }

    @patch("dotenv.load_dotenv")
    def test_dotenv_loads_project_file_without_overriding_environment(self, load_mock):
        module_path = Path(context_module.__file__).resolve()
        spec = importlib.util.spec_from_file_location("_context_dotenv_test", module_path)
        isolated_module = importlib.util.module_from_spec(spec)

        spec.loader.exec_module(isolated_module)

        load_mock.assert_called_once_with(module_path.parent.parent / ".env", override=False)

    @patch("reasoning.context.OpenAI")
    def test_request_sends_configuration_image_and_indexed_candidates(self, openai_mock):
        client = openai_mock.return_value
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"selected_index": 1, "reason": "matches image"}'
                    )
                )
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "formula.png"
            image_path.write_bytes(b"image-bytes")
            with patch.dict(os.environ, self.environment, clear=True):
                result = _request_context(str(image_path), self.candidates)

        self.assertEqual(result, {"selected_index": 1, "reason": "matches image"})
        openai_mock.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.example.test/v1",
            timeout=12.5,
        )
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "vision-model")
        self.assertEqual(request["response_format"], {"type": "json_object"})
        system_content = request["messages"][0]["content"]
        self.assertIn("existing candidate", system_content)
        self.assertIn("visibly present", system_content)
        self.assertIn("structurally incomplete", system_content)
        self.assertIn("structural cleanliness", system_content)
        self.assertIn("Do not generate, correct, or simplify LaTeX", system_content)
        self.assertIn("zero-based integer selected_index", system_content)
        content = request["messages"][1]["content"]
        indexed_candidates = json.loads(content[0]["text"].split("\n", 1)[1])
        self.assertEqual(
            indexed_candidates,
            [{"index": 0, "latex": "x"}, {"index": 1, "latex": "y"}],
        )
        data_url = content[1]["image_url"]["url"]
        self.assertTrue(data_url.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(data_url.split(",", 1)[1]), b"image-bytes")

    @patch("reasoning.context.OpenAI")
    def test_default_configuration_and_whitespace_are_normalized(self, openai_mock):
        client = openai_mock.return_value
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"selected_index": 0, "reason": "matches image"}'
                    )
                )
            ]
        )
        environment = {
            "OPENAI_API_KEY": " test-key ",
            "OPENAI_BASE_URL": " ",
            "OPENAI_MODEL": " vision-model ",
        }
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "formula.png"
            image_path.write_bytes(b"image-bytes")
            with patch.dict(os.environ, environment, clear=True):
                result = _request_context(str(image_path), self.candidates)

        self.assertEqual(result["selected_index"], 0)
        openai_mock.assert_called_once_with(
            api_key="test-key",
            base_url=None,
            timeout=30.0,
        )
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["model"],
            "vision-model",
        )

    @patch("reasoning.context.OpenAI")
    def test_missing_or_invalid_configuration_does_not_call_api(self, openai_mock):
        cases = [
            ({}, "OPENAI_API_KEY"),
            ({"OPENAI_API_KEY": " "}, "OPENAI_API_KEY"),
            ({"OPENAI_API_KEY": "test-key"}, "OPENAI_MODEL"),
            (
                {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": " "},
                "OPENAI_MODEL",
            ),
            *[
                (
                    {
                        "OPENAI_API_KEY": "test-key",
                        "OPENAI_MODEL": "vision-model",
                        "OPENAI_TIMEOUT_SECONDS": timeout,
                    },
                    "OPENAI_TIMEOUT_SECONDS",
                )
                for timeout in ("0", "-1", "invalid", "nan", "inf", "-inf")
            ],
        ]
        for environment, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with patch.dict(os.environ, environment, clear=True):
                    result = choose_with_context("image.png", self.candidates)
                self.assertIsNone(result["selected_index"])
                self.assertIn(expected_error, result["error"])
        openai_mock.assert_not_called()

    @patch("reasoning.context.OpenAI")
    def test_missing_image_does_not_call_api(self, openai_mock):
        with patch.dict(os.environ, self.environment, clear=True):
            result = choose_with_context("missing.png", self.candidates)

        self.assertIsNone(result["selected_index"])
        self.assertIn("FileNotFoundError", result["error"])
        openai_mock.assert_not_called()

    def test_image_types_are_inferred_from_supported_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix, image_type in (
                (".png", "image/png"),
                (".jpg", "image/jpeg"),
                (".jpeg", "image/jpeg"),
                (".gif", "image/gif"),
                (".webp", "image/webp"),
            ):
                with self.subTest(suffix=suffix):
                    image_path = Path(directory) / f"formula{suffix}"
                    image_path.write_bytes(b"image-bytes")
                    data_url = _read_image_data_url(str(image_path))
                    self.assertTrue(data_url.startswith(f"data:{image_type};base64,"))
            for filename in ("formula.bmp", "formula"):
                with self.subTest(filename=filename):
                    image_path = Path(directory) / filename
                    image_path.write_bytes(b"image-bytes")
                    with self.assertRaises(ValueError):
                        _read_image_data_url(str(image_path))

    @patch("reasoning.context.OpenAI")
    def test_invalid_api_content_returns_error_instead_of_guessing(self, openai_mock):
        client = openai_mock.return_value
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "formula.png"
            image_path.write_bytes(b"image-bytes")
            for content in ("not JSON", ""):
                with self.subTest(content=content):
                    client.chat.completions.create.return_value = SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
                    )
                    with patch.dict(os.environ, self.environment, clear=True):
                        result = choose_with_context(str(image_path), self.candidates)
                    self.assertIsNone(result["selected_index"])
                    self.assertTrue(result["error"])


class ContextRefineTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"engine": "a", "latex": "x", "score": None, "error": None},
            {"engine": "b", "latex": "y", "score": None, "error": None},
        ]

    @patch("reasoner.choose_with_context")
    def test_refine_uses_context_choice_and_records_change(self, choose_mock):
        choose_mock.return_value = {
            "selected_index": 1,
            "reason": "second candidate matches the image",
            "error": None,
        }
        original = copy.deepcopy(self.candidates)

        result = refine("image.png", self.candidates)

        self.assertEqual(result["raw_latex"], "y")
        self.assertEqual(result["final_latex"], "y")
        self.assertEqual(result["confidence"], "medium")
        self.assertFalse(result["need_review"])
        self.assertIsNone(result["risk_score"])
        self.assertEqual(
            result["changes"],
            [
                {
                    "rule": "context_candidate_selection",
                    "before": "x",
                    "after": "y",
                    "selected_index": 1,
                    "reason": "second candidate matches the image",
                }
            ],
        )
        self.assertEqual(self.candidates, original)

    @patch("reasoner.choose_with_context")
    def test_context_selection_and_whitespace_trim_are_recorded_separately(self, choose_mock):
        self.candidates[1]["latex"] = " y "
        choose_mock.return_value = {
            "selected_index": 1,
            "reason": "second candidate matches",
            "error": None,
        }

        result = refine("image.png", self.candidates)

        self.assertEqual(result["raw_latex"], " y ")
        self.assertEqual(result["final_latex"], "y")
        self.assertEqual(
            result["changes"],
            [
                {
                    "rule": "context_candidate_selection",
                    "before": "x",
                    "after": " y ",
                    "selected_index": 1,
                    "reason": "second candidate matches",
                },
                {
                    "rule": "trim_outer_whitespace",
                    "before": " y ",
                    "after": "y",
                },
            ],
        )

    @patch("reasoner.choose_with_context")
    def test_selecting_first_candidate_does_not_record_a_change(self, choose_mock):
        choose_mock.return_value = {
            "selected_index": 0,
            "reason": "first candidate matches",
            "error": None,
        }

        result = refine("image.png", self.candidates)

        self.assertEqual(result["raw_latex"], "x")
        self.assertEqual(result["changes"], [])
        self.assertFalse(result["need_review"])

    @patch("reasoner.choose_with_context")
    def test_context_failure_preserves_first_candidate_and_requires_review(self, choose_mock):
        choose_mock.return_value = {
            "selected_index": None,
            "reason": "",
            "error": "ConnectionError: offline",
        }

        result = refine("image.png", self.candidates)

        self.assertEqual(result["raw_latex"], "x")
        self.assertEqual(result["final_latex"], "x")
        self.assertEqual(result["confidence"], "low")
        self.assertTrue(result["need_review"])
        self.assertEqual(result["changes"], [])

    @patch("reasoner.choose_with_context")
    def test_context_choice_still_requires_review_for_structure_error(self, choose_mock):
        self.candidates[1]["latex"] = r"\frac{x}"
        choose_mock.return_value = {
            "selected_index": 1,
            "reason": "matches handwriting",
            "error": None,
        }

        result = refine("image.png", self.candidates)

        self.assertEqual(result["raw_latex"], r"\frac{x}")
        self.assertEqual(result["confidence"], "low")
        self.assertTrue(result["need_review"])


if __name__ == "__main__":
    unittest.main()
