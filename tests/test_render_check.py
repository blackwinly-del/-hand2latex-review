import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reasoning.render_check import _PROJECT_ROOT, check_renderable


def _renderer_unavailable_reason():
    """真调 node 的用例需要本机同时具备 node 和 node_modules/katex。

    安装包按设计不带 node_modules（体积大，且终端用户用不到渲染校验），
    所以在交付包里这几个用例没有运行条件。缺条件时应当 skip 而不是 ERROR：
    ERROR 会让人以为代码坏了，而真实原因是"这台机器没装渲染环境"。
    """
    if shutil.which("node") is None:
        return "本机没有 node，跳过真调渲染器的用例"
    if not (Path(_PROJECT_ROOT) / "node_modules" / "katex" / "package.json").is_file():
        return "没有 node_modules/katex（安装包按设计不带 node_modules），跳过真调渲染器的用例"
    return None


_RENDERER_SKIP_REASON = _renderer_unavailable_reason()


class RenderCheckTests(unittest.TestCase):
    @unittest.skipIf(_RENDERER_SKIP_REASON, _RENDERER_SKIP_REASON or "")
    def test_valid_latex_is_renderable(self):
        result = check_renderable(r"\frac{x^{2}}{2}")

        self.assertEqual(result, {"renderable": True, "error": None})

    @unittest.skipIf(_RENDERER_SKIP_REASON, _RENDERER_SKIP_REASON or "")
    def test_undefined_command_returns_render_error_without_rewriting(self):
        latex = r"\badmacro{x}"

        result = check_renderable(latex)

        self.assertFalse(result["renderable"])
        self.assertIn("Undefined control sequence", result["error"])
        self.assertEqual(latex, r"\badmacro{x}")

    @unittest.skipIf(_RENDERER_SKIP_REASON, _RENDERER_SKIP_REASON or "")
    def test_unbalanced_braces_return_render_error(self):
        result = check_renderable(r"\frac{x}{2")

        self.assertFalse(result["renderable"])
        self.assertTrue(result["error"])

    def test_non_string_latex_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "latex must be a string"):
            check_renderable(None)

    @patch("reasoning.render_check.subprocess.run")
    def test_missing_node_is_checker_error(self, run_mock):
        run_mock.side_effect = FileNotFoundError

        with self.assertRaisesRegex(RuntimeError, "Node.js is required"):
            check_renderable("x")

    @patch("reasoning.render_check.subprocess.run")
    def test_timeout_is_checker_error(self, run_mock):
        run_mock.side_effect = subprocess.TimeoutExpired(cmd="node", timeout=10)

        with self.assertRaisesRegex(RuntimeError, "timed out"):
            check_renderable("x")

    @patch("reasoning.render_check.subprocess.run")
    def test_checker_failure_is_not_formula_error(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args="node", returncode=1, stdout="", stderr="renderer unavailable"
        )

        with self.assertRaisesRegex(RuntimeError, "renderer unavailable"):
            check_renderable("x")

    @patch("reasoning.render_check.subprocess.run")
    def test_permission_failure_is_checker_error(self, run_mock):
        run_mock.side_effect = PermissionError("permission denied")

        with self.assertRaisesRegex(RuntimeError, "could not start"):
            check_renderable("x")

    @patch("reasoning.render_check.subprocess.run")
    def test_invalid_output_decoding_is_checker_error(self, run_mock):
        run_mock.side_effect = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")

        with self.assertRaisesRegex(RuntimeError, "invalid output"):
            check_renderable("x")

    @patch("reasoning.render_check.subprocess.run")
    def test_invalid_parse_response_is_checker_error(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args="node", returncode=2, stdout="not json", stderr=""
        )

        with self.assertRaisesRegex(RuntimeError, "invalid output"):
            check_renderable("x")

    @patch("reasoning.render_check.subprocess.run")
    def test_missing_parse_error_is_checker_error(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args="node", returncode=2, stdout="{}", stderr=""
        )

        with self.assertRaisesRegex(RuntimeError, "invalid output"):
            check_renderable("x")

    @unittest.skipIf(_RENDERER_SKIP_REASON, _RENDERER_SKIP_REASON or "")
    def test_project_local_renderer_works_outside_project_directory(self):
        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                result = check_renderable("x^{2}")
            finally:
                os.chdir(original_directory)

        self.assertEqual(result, {"renderable": True, "error": None})

    @patch("reasoning.render_check.subprocess.run")
    def test_latex_is_passed_as_json_without_shell(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args="node", returncode=0, stdout='{"error": null}', stderr=""
        )
        latex = 'x"; $(touch should_not_exist)'

        check_renderable(latex)

        arguments = run_mock.call_args
        self.assertEqual(arguments.args[0][:2], ["node", "-e"])
        self.assertEqual(json.loads(arguments.kwargs["input"]), {"latex": latex})
        self.assertEqual(arguments.kwargs["encoding"], "utf-8")
        self.assertFalse(arguments.kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
