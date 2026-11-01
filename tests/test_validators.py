import unittest

from reasoning.validators import validate_structure


class ValidateStructureTests(unittest.TestCase):
    def test_valid_pairing_returns_no_issues(self):
        valid_inputs = [
            "\\frac{x^2}{2}",
            "\\left(\\frac{x}{2}\\right)",
            "\\left\\{x\\right\\}",
            "\\leftarrow x \\rightarrow",
            "\\{x\\}",
            "\\(x\\)",
            "\\[x\\]",
            "\\begin{aligned}x&=1\\\\y&=2\\end{aligned}",
            "\\frac12",
            "x^2 + y_{i} + z^\\alpha",
            "x\\_2",
            "x^2_3",
            "x_1^2",
            "x^{2^3}",
            "x_{1_{2}}",
            "{x^2}^3",
            "x^2 + y^3",
        ]

        for latex in valid_inputs:
            with self.subTest(latex=latex):
                self.assertEqual(validate_structure(latex), [])

    def test_empty_input_returns_empty_issue(self):
        for latex in ("", " \n\t"):
            with self.subTest(latex=latex):
                self.assertEqual(validate_structure(latex), ["empty_latex"])

    def test_non_string_input_raises_type_error(self):
        with self.assertRaises(TypeError):
            validate_structure(None)

    def test_crossed_brackets_are_rejected_despite_equal_counts(self):
        self.assertEqual(validate_structure("{[}]"), ["unbalanced_brackets"])

    def test_unclosed_and_extra_brackets_are_rejected(self):
        for latex in ("(x", "x)", "{x"):
            with self.subTest(latex=latex):
                self.assertIn("unbalanced_brackets", validate_structure(latex))

    def test_unmatched_left_and_right_are_rejected(self):
        cases = ["\\left(x)", "(x)\\right"]

        for latex in cases:
            with self.subTest(latex=latex):
                self.assertEqual(
                    validate_structure(latex), ["unbalanced_left_right"]
                )

    def test_double_backslash_does_not_hide_following_bracket(self):
        self.assertEqual(validate_structure("\\\\{x"), ["unbalanced_brackets"])

    def test_mismatched_or_unclosed_environments_are_rejected(self):
        cases = [
            "\\begin{aligned}x\\end{matrix}",
            "\\begin{aligned}x",
            "x\\end{aligned}",
            "\\begin x\\end{x}",
        ]

        for latex in cases:
            with self.subTest(latex=latex):
                self.assertIn("unbalanced_environments", validate_structure(latex))

    def test_frac_with_missing_arguments_is_rejected(self):
        for latex in ("\\frac", "\\frac{x}", "{\\frac}"):
            with self.subTest(latex=latex):
                self.assertIn("invalid_frac", validate_structure(latex))

    def test_missing_or_adjacent_script_arguments_are_rejected(self):
        for latex in ("x^", "^2", "x^^2", "x_", "{_2}"):
            with self.subTest(latex=latex):
                self.assertIn("invalid_scripts", validate_structure(latex))

    def test_repeated_scripts_on_one_base_are_rejected(self):
        for latex in ("x^2^3", "x_1_2", "x^{2}^{3}"):
            with self.subTest(latex=latex):
                self.assertIn("invalid_scripts", validate_structure(latex))


if __name__ == "__main__":
    unittest.main()
