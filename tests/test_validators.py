import copy
import unittest

from reasoning.validators import find_ambiguous_glyph_conflicts, validate_structure


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


class AmbiguousGlyphConflictTests(unittest.TestCase):
    def test_both_directions_and_span_contract(self):
        cases = [
            (["0", "o"], ["0", "o"]),
            (["o", "0"], ["o", "0"]),
        ]
        for latexes, expected_texts in cases:
            with self.subTest(latexes=latexes):
                candidates = [{"latex": latex} for latex in latexes]
                conflicts = find_ambiguous_glyph_conflicts(candidates)

                self.assertEqual(len(conflicts), 1)
                conflict = conflicts[0]
                self.assertEqual(conflict["issue_type"], "ambiguous_glyph_conflict")
                self.assertEqual(conflict["candidate_indices"], [0, 1])
                self.assertEqual(conflict["position"], 0)
                self.assertEqual(conflict["glyph_pair"], ["0", "o"])
                self.assertEqual(len(conflict["spans"]), 2)
                for index, span in enumerate(conflict["spans"]):
                    self.assertEqual(span["target"], f"candidate:{index}")
                    self.assertEqual(span["start"], 0)
                    self.assertEqual(span["end"], 1)
                    self.assertEqual(span["text"], expected_texts[index])
                    self.assertEqual(span["source_revision"], 0)

    def test_mixed_and_repeated_differences_are_independently_detected(self):
        mixed = find_ambiguous_glyph_conflicts([{"latex": "a0b1"}, {"latex": "aob2"}])
        self.assertEqual(len(mixed), 1)
        self.assertEqual(mixed[0]["position"], 1)

        repeated = find_ambiguous_glyph_conflicts([{"latex": "0o0"}, {"latex": "o0o"}])
        self.assertEqual([conflict["position"] for conflict in repeated], [0, 1, 2])

    def test_different_lengths_and_unrelated_differences_do_not_trigger(self):
        cases = [
            [{"latex": "0"}, {"latex": "o0"}],
            [{"latex": "x"}, {"latex": "y"}],
            [{"latex": "same"}, {"latex": "same"}],
        ]
        for candidates in cases:
            with self.subTest(candidates=candidates):
                self.assertEqual(find_ambiguous_glyph_conflicts(candidates), [])

    def test_three_candidates_have_unique_valid_span_ids(self):
        candidates = [{"latex": "0a"}, {"latex": "oa"}, {"latex": "ob"}]

        conflicts = find_ambiguous_glyph_conflicts(candidates)

        self.assertEqual(len(conflicts), 2)
        spans = [span for conflict in conflicts for span in conflict["spans"]]
        self.assertEqual(len({span["span_id"] for span in spans}), 4)
        for span in spans:
            candidate_index = int(span["target"].split(":", 1)[1])
            self.assertEqual(
                span["text"],
                candidates[candidate_index]["latex"][span["start"]:span["end"]],
            )

    def test_empty_single_and_invalid_candidate_boundaries(self):
        self.assertEqual(find_ambiguous_glyph_conflicts([]), [])
        self.assertEqual(find_ambiguous_glyph_conflicts([{"latex": "0"}]), [])
        with self.assertRaises(TypeError):
            find_ambiguous_glyph_conflicts(["0"])
        with self.assertRaises(ValueError):
            find_ambiguous_glyph_conflicts([{"latex": " "}])
        with self.assertRaises(ValueError):
            find_ambiguous_glyph_conflicts([{"latex": "0", "error": "failed"}])

    def test_inputs_are_not_modified_and_invalid_inputs_are_rejected(self):
        candidates = [{"latex": "0(x^3)"}, {"latex": "o(x^3)"}]
        snapshot = copy.deepcopy(candidates)
        find_ambiguous_glyph_conflicts(candidates)
        self.assertEqual(candidates, snapshot)

        with self.assertRaises(TypeError):
            find_ambiguous_glyph_conflicts(None)
        with self.assertRaises(ValueError):
            find_ambiguous_glyph_conflicts([{"latex": "0"}, {}])
        with self.assertRaises(TypeError):
            find_ambiguous_glyph_conflicts([{"latex": None}])


if __name__ == "__main__":
    unittest.main()
