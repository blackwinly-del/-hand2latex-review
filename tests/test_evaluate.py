import unittest

from reasoning.evaluate import evaluate_refinement


def make_sample(ground_truth, raw, final, latency, review, renderable=None):
    sample = {
        "ground_truth": ground_truth,
        "refine_result": {
            "raw_latex": raw,
            "final_latex": final,
            "need_review": review,
        },
        "latency_ms": latency,
    }
    if renderable is not None:
        sample["renderable"] = renderable
    return sample


class EvaluateRefinementTests(unittest.TestCase):
    def test_computes_all_metrics_on_the_same_samples(self):
        samples = [
            make_sample("x", " x ", "x", 10, False, True),
            make_sample("y", "y", "z", 20, True, False),
            make_sample("z", "q", "z", 30, False, True),
            make_sample("a", "b", "a", 40, True, True),
        ]

        result = evaluate_refinement(samples)

        self.assertEqual(result["sample_count"], 4)
        self.assertEqual(result["raw_correct_count"], 2)
        self.assertEqual(result["final_correct_count"], 3)
        self.assertEqual(result["erroneous_rewrite_count"], 1)
        self.assertEqual(result["review_count"], 2)
        self.assertEqual(result["raw_exact_accuracy"], 0.5)
        self.assertEqual(result["final_exact_accuracy"], 0.75)
        self.assertEqual(result["erroneous_rewrite_rate"], 0.5)
        self.assertEqual(result["renderable_rate"], 0.75)
        self.assertEqual(result["human_review_rate"], 0.5)
        self.assertEqual(result["refine_latency_ms"], {"median": 25, "p95": 40})

    def test_only_outer_whitespace_is_normalized_for_exact_match(self):
        result = evaluate_refinement(
            [make_sample("\\text{a b}", "\\text{a  b}", "\\text{a  b}", 5, False)]
        )

        self.assertEqual(result["raw_exact_accuracy"], 0)
        self.assertEqual(result["final_exact_accuracy"], 0)
        self.assertIsNone(result["erroneous_rewrite_rate"])
        self.assertIsNone(result["renderable_rate"])
        self.assertEqual(result["refine_latency_ms"], {"median": 5, "p95": 5})

    def test_empty_samples_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_refinement([])

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(TypeError):
            evaluate_refinement(None)
        with self.assertRaises(ValueError):
            evaluate_refinement([make_sample(" ", "x", "x", 1, False)])
        with self.assertRaises(ValueError):
            evaluate_refinement([make_sample("x", "x", "x", -1, False)])
        with self.assertRaises(TypeError):
            evaluate_refinement([make_sample("x", "x", "x", True, False)])
        for latency in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(latency=latency):
                with self.assertRaises(ValueError):
                    evaluate_refinement([make_sample("x", "x", "x", latency, False)])

    def test_statistical_and_renderable_boundaries(self):
        samples = [
            make_sample("x", "x", "x", latency, False, False)
            for latency in range(1, 21)
        ]

        result = evaluate_refinement(samples)

        self.assertEqual(result["refine_latency_ms"]["p95"], 19)
        self.assertEqual(result["refine_latency_ms"]["median"], 10.5)
        self.assertEqual(result["renderable_rate"], 0.0)
        with self.assertRaises(TypeError):
            evaluate_refinement(
                [make_sample("x", "x", "x", 1, False, "yes")]
            )

    def test_partial_renderable_flags_are_rejected(self):
        samples = [
            make_sample("x", "x", "x", 1, False, True),
            make_sample("y", "y", "y", 2, False),
        ]

        with self.assertRaises(ValueError):
            evaluate_refinement(samples)


if __name__ == "__main__":
    unittest.main()
