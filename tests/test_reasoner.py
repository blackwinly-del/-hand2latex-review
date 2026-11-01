import copy
import unittest

from reasoner import deduplicate_candidates, normalize_latex, refine


def make_candidate(engine, latex, error=None):
    return {
        "engine": engine,
        "latex": latex,
        "score": None,
        "latency_ms": 0,
        "error": error,
    }


class NormalizeLatexTests(unittest.TestCase):
    def test_trims_only_outer_whitespace(self):
        self.assertEqual(normalize_latex("  \\text{a  b} \n"), "\\text{a  b}")

    def test_empty_input_returns_empty_string(self):
        for latex in ("", " \n\t"):
            with self.subTest(latex=latex):
                self.assertEqual(normalize_latex(latex), "")

    def test_non_string_input_raises_type_error(self):
        with self.assertRaises(TypeError):
            normalize_latex(None)


class DeduplicateCandidatesTests(unittest.TestCase):
    def test_keeps_first_original_candidate_without_mutating_input(self):
        candidates = [
            {
                "engine": "pp_formulanet_l",
                "latex": "  \\frac{x^2}{2}  ",
                "score": None,
                "latency_ms": 10,
                "error": None,
            },
            {
                "engine": "unimernet_tiny",
                "latex": "\\frac{x^2}{2}",
                "score": None,
                "latency_ms": 12,
                "error": None,
            },
            {
                "engine": "unimernet_tiny",
                "latex": "\\frac{x^2}{3}",
                "score": None,
                "latency_ms": 12,
                "error": None,
            },
        ]
        snapshot = copy.deepcopy(candidates)

        result = deduplicate_candidates(candidates)

        self.assertEqual(result, [candidates[0], candidates[2]])
        self.assertIs(result[0], candidates[0])
        self.assertIs(result[1], candidates[2])
        self.assertEqual(result[0]["latex"], "  \\frac{x^2}{2}  ")
        self.assertEqual(candidates, snapshot)

    def test_internal_whitespace_differences_are_not_duplicates(self):
        candidates = [{"latex": "\\text{a b}"}, {"latex": "\\text{a  b}"}]

        self.assertEqual(deduplicate_candidates(candidates), candidates)

    def test_empty_and_blank_candidates_return_empty_list(self):
        self.assertEqual(deduplicate_candidates([]), [])
        self.assertEqual(deduplicate_candidates([{"latex": " \n"}]), [])

    def test_invalid_candidates_raise_clear_errors(self):
        cases = [
            (None, TypeError),
            ({}, ValueError),
            ({"latex": None}, TypeError),
        ]

        for candidate, error_type in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(error_type):
                    deduplicate_candidates([candidate])


class RefineTests(unittest.TestCase):
    def test_empty_or_failed_candidates_require_review(self):
        cases = [
            [],
            [make_candidate("pp_formulanet_l", "")],
            [make_candidate("pp_formulanet_l", "x", "recognition failed")],
        ]
        expected = {
            "raw_latex": "",
            "final_latex": "",
            "confidence": "low",
            "changes": [],
            "need_review": True,
            "risk_score": None,
        }

        for candidates in cases:
            with self.subTest(candidates=candidates):
                self.assertEqual(refine("unused.png", candidates), expected)

    def test_single_valid_candidate_preserves_raw_and_records_trim(self):
        candidates = [make_candidate("pp_formulanet_l", "  \\frac{x^2}{2}  ")]
        snapshot = copy.deepcopy(candidates)

        result = refine("unused.png", candidates)

        self.assertEqual(
            result,
            {
                "raw_latex": "  \\frac{x^2}{2}  ",
                "final_latex": "\\frac{x^2}{2}",
                "confidence": "medium",
                "changes": [
                    {
                        "rule": "trim_outer_whitespace",
                        "before": "  \\frac{x^2}{2}  ",
                        "after": "\\frac{x^2}{2}",
                    }
                ],
                "need_review": False,
                "risk_score": None,
            },
        )
        self.assertEqual(candidates, snapshot)

    def test_cross_engine_agreement_is_high_confidence(self):
        candidates = [
            make_candidate("pp_formulanet_l", " x+1 "),
            make_candidate("unimernet_tiny", "x+1"),
        ]

        result = refine("unused.png", candidates)

        self.assertEqual(result["confidence"], "high")
        self.assertFalse(result["need_review"])
        self.assertEqual(result["raw_latex"], " x+1 ")

    def test_same_engine_duplicates_are_only_medium_confidence(self):
        candidates = [
            make_candidate("pp_formulanet_l", "x+1"),
            make_candidate("pp_formulanet_l", " x+1 "),
        ]

        result = refine("unused.png", candidates)

        self.assertEqual(result["confidence"], "medium")
        self.assertFalse(result["need_review"])

    def test_conflicting_candidates_require_review_without_majority_vote(self):
        candidates = [
            make_candidate("pp_formulanet_l", "\\frac{x}{2}"),
            make_candidate("unimernet_tiny", "\\frac{x}{2}"),
            make_candidate("unimernet_tiny", "\\frac{x}{3}"),
        ]

        result = refine("unused.png", candidates)

        self.assertEqual(result["raw_latex"], "\\frac{x}{2}")
        self.assertEqual(result["final_latex"], "\\frac{x}{2}")
        self.assertEqual(result["confidence"], "low")
        self.assertTrue(result["need_review"])
        self.assertEqual(result["changes"], [])

    def test_structure_error_is_preserved_for_review(self):
        for latex in ("\\frac{x}", "x^2^3"):
            with self.subTest(latex=latex):
                result = refine(
                    "unused.png", [make_candidate("pp_formulanet_l", latex)]
                )

                self.assertEqual(result["raw_latex"], latex)
                self.assertEqual(result["final_latex"], latex)
                self.assertEqual(result["confidence"], "low")
                self.assertTrue(result["need_review"])

    def test_mathematical_validity_is_not_corrected(self):
        result = refine(
            "unused.png", [make_candidate("pp_formulanet_l", "\\frac{1}{0}")]
        )

        self.assertEqual(result["final_latex"], "\\frac{1}{0}")
        self.assertEqual(result["confidence"], "medium")
        self.assertFalse(result["need_review"])

    def test_error_candidate_does_not_hide_valid_duplicate(self):
        candidates = [
            make_candidate("pp_formulanet_l", "x+1", "recognition failed"),
            make_candidate("unimernet_tiny", "x+1"),
        ]

        result = refine("unused.png", candidates)

        self.assertEqual(result["raw_latex"], "x+1")
        self.assertEqual(result["confidence"], "medium")
        self.assertFalse(result["need_review"])

    def test_invalid_outer_candidates_type_raises_type_error(self):
        with self.assertRaises(TypeError):
            refine("unused.png", None)


if __name__ == "__main__":
    unittest.main()
