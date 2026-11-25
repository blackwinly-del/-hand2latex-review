import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reasoner
from reasoning.context_benchmark import (
    DEFAULT_INPUT,
    replay_context_benchmark,
    run_context_benchmark,
)


# ---------------------------------------------------------------------------
# 存档数据是否在仓库里
#
# 下面这几个文件不是"可以随手造"的测试夹具，而是**真实 API 响应的存档**：
#   artifacts/context_conflict_samples.json       —— 一次真实采样的候选集
#   artifacts/context_conflict_samples_v2.json    —— 扩到 10 条均衡冲突
#   artifacts/context_stability_samples_8_9_run_{1,2,3}.json —— sample_8/9 各跑三轮的稳定性
#
# 它们的价值恰恰在于"是真实模型输出"——自己合成一份再让测试通过，测试就变成了
# 自证（断言"我造的数据符合我造的数据"），比直接跳过更糟。
#
# 这 5 个文件在 2026-11-25 核对时已不在工作区，也不在 h2l-backups 的备份里，
# 说明不是那次改动弄丢的。README 第 9 节引用的同类证据文件也一并缺失，
# 已在 docs/成果汇报_2026-11-25.md 的 7.2 节列出全部清单和处理选项。
#
# 处理方式：只给依赖这些文件的 4 个用例加前置条件，其余 15 个用临时构造数据的
# 用例照常运行——不因为缺存档就把整个上下文基准套件停掉。
# 把文件补回来（重跑采集）之后，这 4 个用例会自动恢复运行，无需改代码。
_ARTIFACTS_ROOT = Path(__file__).resolve().parent.parent / "artifacts"

_CONFLICT_SAMPLES = _ARTIFACTS_ROOT / "context_conflict_samples.json"
_CONFLICT_SAMPLES_V2 = _ARTIFACTS_ROOT / "context_conflict_samples_v2.json"
_STABILITY_RUNS = [
    _ARTIFACTS_ROOT / f"context_stability_samples_8_9_run_{index}.json"
    for index in (1, 2, 3)
]

_NEED_REAL_SAMPLES = "缺少真实 API 响应存档（artifacts/context_conflict_samples*.json），跳过"


def _has(paths) -> bool:
    return all(path.is_file() for path in paths)


def make_sample(sample_id, ground_truth, expected_index, latexes):
    return {
        "sample_id": sample_id,
        "image_path": "image.png",
        "ground_truth": ground_truth,
        "expected_index": expected_index,
        "candidates": [
            {
                "engine": f"engine_{index}",
                "latex": latex,
                "score": None,
                "latency_ms": 0,
                "error": None,
            }
            for index, latex in enumerate(latexes)
        ],
    }


class ContextBenchmarkTests(unittest.TestCase):
    @patch("reasoning.context_benchmark.check_renderable")
    @patch("reasoning.context_benchmark.choose_with_context")
    def test_runner_reuses_one_response_and_writes_same_sample_metrics(self, choose_mock, render_mock):
        render_mock.return_value = {"renderable": True, "error": None}
        samples = [
            make_sample("select_second", "y", 1, ["x", "y"]),
            make_sample("fallback_keeps_first", "z", 0, ["z", "q"]),
        ]
        choose_mock.side_effect = [
            {"selected_index": 1, "reason": "matches", "error": None},
            {"selected_index": None, "reason": "", "error": "ConnectionError"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            output_path = Path(directory) / "results.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": samples}),
                encoding="utf-8",
            )

            report = run_context_benchmark(input_path, output_path)

            saved_report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(choose_mock.call_count, 2)
        self.assertEqual(saved_report, report)
        self.assertEqual(report["summary"]["raw_exact_accuracy"], 0.5)
        self.assertEqual(report["summary"]["final_exact_accuracy"], 1.0)
        self.assertEqual(report["summary"]["context_selection_accuracy"], 0.5)
        self.assertEqual(report["summary"]["context_fallback_rate"], 0.5)
        self.assertEqual(report["summary"]["correct_final_review_rate"], 0.5)
        self.assertEqual(report["summary"]["renderable_rate"], 1.0)
        self.assertEqual(render_mock.call_count, 2)
        self.assertIn("context_latency_ms", report["summary"])
        self.assertNotIn("refine_latency_ms", report["summary"])
        self.assertFalse(report["results"][0]["refine_result"]["need_review"])
        self.assertTrue(report["results"][1]["refine_result"]["need_review"])

    @unittest.skipUnless(_has([_CONFLICT_SAMPLES_V2]), _NEED_REAL_SAMPLES)
    @patch("reasoning.context_benchmark.check_renderable")
    @patch("reasoning.context_benchmark.choose_with_context")
    def test_expanded_dataset_offline_preserves_inputs_and_structure_review(self, choose_mock, render_mock):
        render_mock.return_value = {"renderable": True, "error": None}
        input_path = DEFAULT_INPUT.with_name("context_conflict_samples_v2.json")
        dataset = json.loads(input_path.read_text(encoding="utf-8"))
        original = copy.deepcopy(dataset)
        choose_mock.side_effect = [
            {
                "selected_index": sample["expected_index"],
                "reason": "offline confirmed selection",
                "error": None,
            }
            for sample in dataset["samples"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "results.json"
            report = run_context_benchmark(input_path, output_path)

        self.assertEqual(dataset, original)
        self.assertEqual(choose_mock.call_count, 10)
        self.assertEqual(render_mock.call_count, 10)
        self.assertEqual(report["summary"]["final_exact_accuracy"], 1.0)
        structure_sample = next(
            result for result in report["results"]
            if result["sample_id"] == "sample_3_faithful_not_structural_repair"
        )
        self.assertEqual(structure_sample["refine_result"]["final_latex"], structure_sample["ground_truth"])
        self.assertEqual(structure_sample["refine_result"]["confidence"], "low")
        self.assertTrue(structure_sample["refine_result"]["need_review"])

    @unittest.skipUnless(_has([_CONFLICT_SAMPLES]), _NEED_REAL_SAMPLES)
    @patch("reasoner.choose_with_context")
    def test_real_structural_repair_failure_now_requires_review(self, choose_mock):
        dataset = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
        sample = dataset["samples"][2]
        choose_mock.return_value = {
            "selected_index": 0,
            "reason": "Candidate 0 appears structurally complete.",
            "error": None,
        }

        result = reasoner.refine(sample["image_path"], sample["candidates"])

        self.assertEqual(result["final_latex"], sample["candidates"][0]["latex"])
        self.assertEqual(result["confidence"], "low")
        self.assertTrue(result["need_review"])

    @patch("reasoning.context_benchmark.check_renderable")
    @patch("reasoner.choose_with_context")
    def test_replay_uses_saved_responses_without_api_and_records_render_errors(self, choose_mock, render_mock):
        sample = make_sample("render_failure", r"\frac{x}", 0, [r"\frac{x}", "x"])
        saved_report = {
            "model": "saved-model",
            "sample_type": "test",
            "evaluation_scope": "saved test scope",
            "results": [
                {
                    **sample,
                    "context_result": {"selected_index": 0, "reason": "saved", "error": None},
                    "latency_ms": 5,
                }
            ],
        }
        render_mock.return_value = {"renderable": False, "error": "ParseError"}
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "saved.json"
            output_path = Path(directory) / "replayed.json"
            input_path.write_text(json.dumps(saved_report), encoding="utf-8")
            original = copy.deepcopy(saved_report)

            report = replay_context_benchmark(input_path, output_path)

            self.assertEqual(json.loads(input_path.read_text(encoding="utf-8")), original)
        choose_mock.assert_not_called()
        render_mock.assert_called_once_with(r"\frac{x}")
        self.assertEqual(report["additional_api_calls"], 0)
        self.assertEqual(report["model"], "saved-model")
        self.assertEqual(report["evaluation_scope"], "saved test scope")
        self.assertIn("independent", report["render_note"])
        self.assertEqual(report["summary"]["renderable_rate"], 0.0)
        self.assertFalse(report["results"][0]["renderable"])
        self.assertTrue(report["results"][0]["refine_result"]["need_review"])

    def test_replay_refuses_to_overwrite_source_report(self):
        with self.assertRaises(ValueError):
            replay_context_benchmark("same.json", "same.json")

    @unittest.skipUnless(_has(_STABILITY_RUNS), _NEED_REAL_SAMPLES)
    def test_sample_9_saved_responses_all_require_review(self):
        for run_index in range(1, 4):
            with self.subTest(run=run_index):
                report = json.loads(
                    Path(f"artifacts/context_stability_samples_8_9_run_{run_index}.json").read_text(
                        encoding="utf-8"
                    )
                )
                sample = next(
                    result for result in report["results"]
                    if result["sample_id"] == "sample_9_little_o_expansion"
                )
                with patch("reasoner.choose_with_context", return_value=sample["context_result"]):
                    result = reasoner.refine(sample["image_path"], sample["candidates"])

                self.assertEqual(result["confidence"], "low")
                self.assertTrue(result["need_review"])
                self.assertEqual(result["final_latex"], sample["refine_result"]["final_latex"])
                self.assertEqual(result["changes"], sample["refine_result"]["changes"])

    @unittest.skipUnless(_has([_CONFLICT_SAMPLES_V2]), _NEED_REAL_SAMPLES)
    def test_expanded_dataset_has_ten_valid_balanced_conflicts(self):
        input_path = DEFAULT_INPUT.with_name("context_conflict_samples_v2.json")
        dataset = json.loads(input_path.read_text(encoding="utf-8"))
        samples = dataset["samples"]

        self.assertEqual(dataset["sample_count"], 10)
        self.assertEqual(len(samples), 10)
        self.assertEqual(len({sample["sample_id"] for sample in samples}), 10)
        self.assertEqual(
            {index: sum(sample["expected_index"] == index for sample in samples) for index in (0, 1)},
            {0: 5, 1: 5},
        )
        for sample in samples:
            self.assertEqual(len(reasoner.deduplicate_candidates(sample["candidates"])), 2)
            self.assertEqual(
                sample["candidates"][sample["expected_index"]]["latex"],
                sample["ground_truth"],
            )

    @patch("reasoning.context_benchmark.choose_with_context")
    def test_invalid_later_sample_is_rejected_before_any_api_call(self, choose_mock):
        samples = [
            make_sample("valid", "x", 0, ["x", "y"]),
            make_sample("invalid", "z", 1, ["z", "q"]),
        ]
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": samples}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                run_context_benchmark(input_path, Path(directory) / "results.json")

        choose_mock.assert_not_called()

    @patch("reasoning.context_benchmark.choose_with_context")
    def test_invalid_image_path_and_candidate_count_are_rejected_before_api(self, choose_mock):
        cases = [
            make_sample("empty_image", "x", 0, ["x", "y"]),
            make_sample("single_candidate", "x", 0, ["x"]),
        ]
        cases[0]["image_path"] = ""
        for sample in cases:
            with self.subTest(sample_id=sample["sample_id"]):
                choose_mock.reset_mock()
                with tempfile.TemporaryDirectory() as directory:
                    input_path = Path(directory) / "samples.json"
                    input_path.write_text(
                        json.dumps({"sample_type": "test", "samples": [sample]}),
                        encoding="utf-8",
                    )
                    with self.assertRaises(ValueError):
                        run_context_benchmark(input_path, Path(directory) / "results.json")
                choose_mock.assert_not_called()

    @patch("reasoning.context_benchmark.choose_with_context")
    def test_later_request_error_preserves_previous_response(self, choose_mock):
        samples = [
            make_sample("valid", "x", 0, ["x", "y"]),
            make_sample("missing_image", "z", 0, ["z", "q"]),
        ]
        samples[1]["image_path"] = "missing.png"
        choose_mock.side_effect = [
            {"selected_index": 0, "reason": "saved", "error": None},
            FileNotFoundError("missing.png"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            output_path = Path(directory) / "results.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": samples}),
                encoding="utf-8",
            )
            with self.assertRaises(FileNotFoundError):
                run_context_benchmark(input_path, output_path)

            checkpoint = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(len(checkpoint["results"]), 1)
        self.assertEqual(checkpoint["results"][0]["sample_id"], "valid")
        self.assertEqual(checkpoint["evaluation_status"], "context_responses_saved_render_pending")

    @patch("reasoning.context_benchmark.check_renderable")
    @patch("reasoning.context_benchmark.choose_with_context")
    def test_render_failure_preserves_saved_context_checkpoint(self, choose_mock, render_mock):
        samples = [
            make_sample("checkpoint_1", "x", 0, ["x", "y"]),
            make_sample("checkpoint_2", "z", 0, ["z", "q"]),
        ]
        choose_mock.return_value = {"selected_index": 0, "reason": "saved", "error": None}
        render_mock.side_effect = [
            {"renderable": True, "error": None},
            RuntimeError("render checker failed"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            output_path = Path(directory) / "results.json"
            replay_path = Path(directory) / "replayed.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": samples}),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                run_context_benchmark(input_path, output_path)

            checkpoint = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(checkpoint["results"]), 2)
            self.assertTrue(all("renderable" not in result for result in checkpoint["results"]))
            render_mock.side_effect = None
            render_mock.return_value = {"renderable": True, "error": None}
            with patch("reasoner.choose_with_context") as refine_choose_mock:
                replayed = replay_context_benchmark(output_path, replay_path)
            refine_choose_mock.assert_not_called()

        self.assertEqual(choose_mock.call_count, 2)
        self.assertEqual(checkpoint["evaluation_status"], "context_responses_saved_render_pending")
        self.assertIsNone(checkpoint["summary"]["renderable_rate"])
        self.assertEqual(replayed["evaluation_status"], "complete")
        self.assertEqual(replayed["summary"]["renderable_rate"], 1.0)

    @patch("reasoning.context_benchmark.check_renderable")
    @patch("reasoning.context_benchmark.choose_with_context")
    def test_refine_failure_preserves_raw_response_and_replays(self, choose_mock, render_mock):
        sample = make_sample("refine_failure", "x", 0, ["x", "y"])
        choose_mock.return_value = {"selected_index": 0, "reason": "saved", "error": None}
        render_mock.return_value = {"renderable": True, "error": None}
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            output_path = Path(directory) / "results.json"
            replay_path = Path(directory) / "replayed.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": [sample]}),
                encoding="utf-8",
            )
            with patch("reasoner.refine", side_effect=RuntimeError("refine failed")):
                with self.assertRaises(RuntimeError):
                    run_context_benchmark(input_path, output_path)

            checkpoint = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIsNone(checkpoint["summary"])
            self.assertEqual(checkpoint["evaluation_status"], "context_response_saved_refine_pending")
            self.assertNotIn("refine_result", checkpoint["results"][0])
            self.assertEqual(checkpoint["results"][0]["context_result"]["selected_index"], 0)
            with patch("reasoner.choose_with_context") as refine_choose_mock:
                replayed = replay_context_benchmark(output_path, replay_path)
            refine_choose_mock.assert_not_called()

        self.assertEqual(replayed["evaluation_status"], "complete")
        self.assertEqual(replayed["summary"]["final_exact_accuracy"], 1.0)

    @patch("reasoning.context_benchmark.choose_with_context")
    def test_run_refuses_to_overwrite_input_dataset(self, choose_mock):
        sample = make_sample("valid", "x", 0, ["x", "y"])
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            original = json.dumps({"sample_type": "test", "samples": [sample]})
            input_path.write_text(original, encoding="utf-8")
            with self.assertRaises(ValueError):
                run_context_benchmark(input_path, input_path)

            self.assertEqual(input_path.read_text(encoding="utf-8"), original)
        choose_mock.assert_not_called()

    @patch("reasoning.context_benchmark.choose_with_context")
    def test_failed_checkpoint_write_preserves_previous_valid_file(self, choose_mock):
        sample = make_sample("valid", "x", 0, ["x", "y"])
        choose_mock.return_value = {"selected_index": 0, "reason": "saved", "error": None}
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            output_path = Path(directory) / "results.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": [sample]}),
                encoding="utf-8",
            )
            output_path.write_text('{"previous": "valid"}', encoding="utf-8")
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    run_context_benchmark(input_path, output_path)

            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                {"previous": "valid"},
            )
            self.assertFalse((Path(directory) / "results.json.tmp").exists())

    @patch("reasoning.context_benchmark.check_renderable")
    @patch("reasoning.context_benchmark.choose_with_context")
    def test_final_replace_failure_preserves_render_pending_checkpoint(self, choose_mock, render_mock):
        sample = make_sample("valid", "x", 0, ["x", "y"])
        choose_mock.return_value = {"selected_index": 0, "reason": "saved", "error": None}
        render_mock.return_value = {"renderable": True, "error": None}
        real_replace = os.replace
        replace_count = 0

        def fail_final_replace(source, destination):
            nonlocal replace_count
            replace_count += 1
            if replace_count == 3:
                raise PermissionError("target temporarily unavailable")
            real_replace(source, destination)

        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            output_path = Path(directory) / "results.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": [sample]}),
                encoding="utf-8",
            )
            with patch("reasoning.context_benchmark.os.replace", side_effect=fail_final_replace):
                with self.assertRaises(PermissionError):
                    run_context_benchmark(input_path, output_path)

            checkpoint = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["evaluation_status"], "context_responses_saved_render_pending")
            self.assertNotIn("renderable", checkpoint["results"][0])
            self.assertFalse((Path(directory) / "results.json.tmp").exists())

    @patch("reasoning.context_benchmark.choose_with_context")
    def test_missing_output_directory_is_rejected_before_api_call(self, choose_mock):
        sample = make_sample("valid", "x", 0, ["x", "y"])
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": [sample]}),
                encoding="utf-8",
            )
            with self.assertRaises(FileNotFoundError):
                run_context_benchmark(
                    input_path,
                    Path(directory) / "missing" / "results.json",
                )

        choose_mock.assert_not_called()

    @patch("reasoning.context_benchmark.choose_with_context")
    def test_duplicate_candidates_are_rejected_before_api_call(self, choose_mock):
        sample = make_sample("duplicate", "x", 0, ["x", "x"])
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "samples.json"
            input_path.write_text(
                json.dumps({"sample_type": "test", "samples": [sample]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                run_context_benchmark(input_path, Path(directory) / "results.json")

        choose_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
