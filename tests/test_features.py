import copy
import unittest

from reasoning.features import FEATURE_NAMES, extract_features


class FeatureExtractionTests(unittest.TestCase):
    def test_feature_order_is_fixed_at_eight(self):
        self.assertEqual(
            FEATURE_NAMES,
            (
                "candidate_count",
                "valid_candidate_count",
                "engine_count",
                "error_candidate_count",
                "structure_issue_count",
                "has_conflict",
                "selected_latex_length",
                "selected_script_count",
            ),
        )
        self.assertEqual(len(extract_features([])), 8)

    def test_empty_candidates_return_zero_vector(self):
        self.assertEqual(extract_features([]), [0.0] * 8)

    def test_single_valid_candidate(self):
        candidates = [{"engine": "pp", "latex": "x^{2}", "error": None}]

        self.assertEqual(
            extract_features(candidates),
            [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 5.0, 1.0],
        )

    def test_duplicates_errors_and_blank_candidates(self):
        candidates = [
            {"engine": "pp", "latex": "x", "error": None},
            {"engine": "pp", "latex": " x ", "error": None},
            {"engine": "pp", "latex": "", "error": "failed"},
            {"engine": "pp", "latex": "   ", "error": None},
        ]

        self.assertEqual(
            extract_features(candidates),
            [4.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0],
        )

    def test_cross_engine_duplicates_keep_all_supporting_engines(self):
        candidates = [
            {"engine": "a", "latex": "x", "error": None},
            {"engine": "b", "latex": " x ", "error": None},
        ]

        self.assertEqual(
            extract_features(candidates),
            [2.0, 1.0, 2.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        )

    def test_conflicting_candidates_and_structure_issues(self):
        candidates = [
            {"engine": "a", "latex": r"\frac{x}", "error": None},
            {"engine": "b", "latex": "y_1", "error": None},
        ]

        self.assertEqual(
            extract_features(candidates),
            [2.0, 2.0, 2.0, 0.0, 1.0, 1.0, 8.0, 0.0],
        )

    def test_input_is_not_modified_and_all_features_are_float(self):
        candidates = [{"engine": "pp", "latex": " x_1 ", "error": None}]
        original = copy.deepcopy(candidates)

        features = extract_features(candidates)

        self.assertEqual(candidates, original)
        self.assertEqual(features, [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 3.0, 1.0])
        self.assertTrue(all(isinstance(value, float) for value in features))

    def test_invalid_candidates_are_rejected(self):
        invalid_types = [None, ["x"], [{"latex": None}]]
        for candidates in invalid_types:
            with self.subTest(candidates=candidates):
                with self.assertRaises(TypeError):
                    extract_features(candidates)

        with self.assertRaises(ValueError):
            extract_features([{"engine": "pp"}])


if __name__ == "__main__":
    unittest.main()
