import json
import unittest
from pathlib import Path

from scripts.import_page_dataset import (
    _MIN_LATEX_CHARS,
    _SCALE,
    _unique_expressions,
)


def _page(*expressions, image="images/page_0001.png"):
    return {
        "image": image,
        "width": 1240,
        "height": 1754,
        "expressions": [
            {"id": f"e{i:02d}", "bbox": [100, 100 + i * 80, 300, 60], "latex": latex, "source": f"train/{i}.inkml"}
            for i, latex in enumerate(expressions, 1)
        ],
    }


class DedupeTests(unittest.TestCase):
    def test_same_latex_on_many_pages_counts_once(self):
        """100 页里只有 370 条唯一公式，同一条被排进 4.5 页。

        不去重的话，出现 13 次的那个公式会被计 13 遍，准确率就成了
        "这个公式识别对没对"的加权结果，不是整页转录准确率。
        """
        pages = [_page("a+b=c", "x^{2}"), _page("a+b=c", "y=1"), _page("a+b=c")]
        unique = _unique_expressions(pages)
        latexes = sorted(item["latex"] for item in unique)
        self.assertEqual(latexes, ["a+b=c", "x^{2}", "y=1"])

    def test_duplicate_count_is_recorded_not_discarded(self):
        """去重但不能把"重复了几次"这个事实丢掉——写进清单方便追溯。"""
        pages = [_page("a+b=c"), _page("a+b=c"), _page("a+b=c")]
        unique = _unique_expressions(pages)
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["duplicate_count"], 3)

    def test_first_occurrence_wins_for_provenance(self):
        """保留第一次出现的 bbox 和来源页，便于回查。"""
        pages = [
            _page("z=1", image="images/page_0001.png"),
            _page("z=1", image="images/page_0009.png"),
        ]
        item = _unique_expressions(pages)[0]
        self.assertEqual(item["page_image"], "images/page_0001.png")
        self.assertEqual(item["duplicate_count"], 2)

    def test_empty_input_yields_nothing(self):
        self.assertEqual(_unique_expressions([]), [])


class ScaleTests(unittest.TestCase):
    def test_scale_matches_real_page_geometry(self):
        """页面按像素是 1240 宽，按点算是 930。

        裁剪坐标用的是像素，pymupdf 的 Rect 用的是点，不换算框会整体偏移——
        第一版漏了这个，裁出来的图全是错位的。
        """
        self.assertAlmostEqual(_SCALE, 0.75, places=6)


class ShortFormulaTests(unittest.TestCase):
    def test_threshold_is_not_zero(self):
        """单个字母（v、n、x）没有转录价值，不该混进真值集。

        把 v 认成 u 和把整个分式结构搞错是两回事，混在一起只会稀释指标。
        """
        self.assertGreater(_MIN_LATEX_CHARS, 1)


class RealManifestTests(unittest.TestCase):
    """对实际导入的清单做检查（文件存在时）。"""

    @classmethod
    def setUpClass(cls):
        cls.path = Path("data/page_math_ground_truth.json")
        cls.manifest = json.loads(cls.path.read_text(encoding="utf-8")) if cls.path.is_file() else None

    def setUp(self):
        if self.manifest is None:
            self.skipTest("尚未导入 page_math 数据集")

    def test_manifest_is_usable_by_existing_evaluator(self):
        """字段要和 evaluate_handwritten / load_manifest 的要求对得上。"""
        for key in ("sample_id", "image_path", "ground_truth"):
            for sample in self.manifest["samples"]:
                self.assertIn(key, sample)
                self.assertTrue(str(sample[key]).strip())

    def test_no_duplicate_ground_truth(self):
        truths = [s["ground_truth"] for s in self.manifest["samples"]]
        self.assertEqual(len(truths), len(set(truths)), "真值集里不该有重复公式")

    def test_all_images_exist(self):
        missing = [s["image_path"] for s in self.manifest["samples"] if not Path(s["image_path"]).is_file()]
        self.assertEqual(missing, [], f"缺 {len(missing)} 张裁切图")

    def test_expanded_beyond_original_twelve(self):
        """第 5 项的目标是把 12 条扩到 60–100 条以上。"""
        self.assertGreaterEqual(self.manifest["sample_count"], 100)

    def test_provenance_records_that_pages_are_combinations(self):
        """清单里必须留下"100 页只是 370 条公式的重复组合"这个事实。

        不留的话，后来的人看到"100 页"会以为有 100 份独立证据。
        """
        prov = self.manifest["provenance"]
        self.assertIn("unique_expressions", prov)
        self.assertLess(prov["unique_expressions"], prov["page_count"] * 20)
        self.assertIn("重复排版", prov["note"])


if __name__ == "__main__":
    unittest.main()
