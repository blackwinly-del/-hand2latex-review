"""把 page_math_dataset 的标注转成项目现有的真值清单格式。

为什么要转：项目里已有的真值清单（`data/handwritten_ground_truth.json`）是
`recognizer` + `refine` 那条线用的，格式是「一张裁切图 + 一条 ground_truth」。
新给的数据集是整页图 + 多条 bbox + 多条 latex，得先裁成单公式图才能进这条线。

数据来源与可信度（重要，别搞混）：
    latex 字段取自 MathWriting 的 `normalizedLabel`，那是 MathWriting 自己的
    人工标注，不是模型生成的。所以它可以当真值用——这一点和整页草稿不同
    （见 workbench/full_page_eval.py 里为什么那边要加门禁）。

    但"100 页"不等于"100 条独立证据"：100 页里只有 **370 条唯一 latex**，
    平均每个公式被排进 4.5 页。做真值集时必须按唯一 latex 去重，否则同一个
    公式会被重复计入准确率，等于给它加权。

用法：
    python -m scripts.import_page_dataset --zip <path> --output data/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# 页面图是 1240x1754 像素，但打开时按点数算是 930x1315.5。
# 裁剪前要乘这个系数，否则框会整体偏移（我第一版就漏了，裁出来全是错位图）。
_PAGE_WIDTH_PX = 1240
_PAGE_WIDTH_PT = 930.0
_SCALE = _PAGE_WIDTH_PT / _PAGE_WIDTH_PX

# 短到没"转录"意义的公式不进真值集：像 v、n、x 这种单个字母，
# 识别对了也不说明什么，识别错了也说明不了模型差——它把"哪个字母"认错
# 和把一整个分式结构搞错完全是两回事。混进去只会稀释指标。
_MIN_LATEX_CHARS = 8


def _iter_annotations(zf: zipfile.ZipFile, prefix: str):
    with zf.open(f"{prefix}annotations.jsonl") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line.decode("utf-8"))


def _unique_expressions(annotations) -> list[dict]:
    """按 latex 去重，保留首次出现的记录（含 bbox 与来源页）。

    去重是这一步的核心。100 页 = 370 条唯一公式的组合重复，不去重的话
    准确率会被那几个出现 10 次以上的公式主导。
    """
    seen: dict[str, dict] = {}
    for page in annotations:
        for expr in page["expressions"]:
            latex = expr["latex"]
            if latex in seen:
                seen[latex]["duplicate_count"] += 1
                continue
            seen[latex] = {
                "latex": latex,
                "bbox": expr["bbox"],
                "page_image": page["image"],
                "source": expr.get("source", ""),
                "duplicate_count": 1,
            }
    return list(seen.values())


def build_manifest(zf: zipfile.ZipFile, prefix: str, out_dir: Path) -> dict:
    """裁出单公式图并组装真值清单。"""
    try:
        import pymupdf
    except ImportError:
        raise SystemExit("需要 pymupdf 来裁图：pip install pymupdf")

    annotations = list(_iter_annotations(zf, prefix))
    unique = _unique_expressions(annotations)

    images_dir = out_dir / "page_math"
    images_dir.mkdir(parents=True, exist_ok=True)

    samples = []
    skipped_short = 0
    cache: dict[str, object] = {}
    for index, item in enumerate(sorted(unique, key=lambda x: x["latex"])):
        if len(item["latex"]) < _MIN_LATEX_CHARS:
            skipped_short += 1
            continue
        page_name = item["page_image"].split("/")[-1]
        if page_name not in cache:
            # 图片在 zip 里，先落到临时位置再让 pymupdf 读。
            # pymupdf 能直接读 bytes，但 open() 要路径或 stream，这里用 stream。
            data = zf.read(f"{prefix}{item['page_image']}")
            cache[page_name] = pymupdf.open(stream=data, filetype="png")
        doc = cache[page_name]
        page = doc[0]
        x, y, w, h = item["bbox"]
        clip = pymupdf.Rect(x * _SCALE, y * _SCALE, (x + w) * _SCALE, (y + h) * _SCALE)
        # 留 2% 边距：紧贴笔迹裁切会让部分笔画落在框外，识别模型看不到。
        pad_x, pad_y = w * 0.02, h * 0.02
        clip = pymupdf.Rect(
            (x - pad_x) * _SCALE, (y - pad_y) * _SCALE,
            (x + w + pad_x) * _SCALE, (y + h + pad_y) * _SCALE,
        )
        sample_id = f"pm_{index:03d}"
        out_path = images_dir / f"{sample_id}.png"
        page.get_pixmap(clip=clip, dpi=200).save(str(out_path))
        samples.append({
            "sample_id": sample_id,
            "image_path": f"data/page_math/{sample_id}.png",
            "ground_truth": item["latex"],
            "human_review": "confirmed_correct",
            "review_note": (
                "latex 取自 MathWriting 的 normalizedLabel（人工标注），"
                f"来源 {item['source']}；该公式在 {item['duplicate_count']} 页中出现过"
            ),
            "source_artifact": item["page_image"],
        })
    for doc in cache.values():
        doc.close()

    manifest = {
        "version": 1,
        "description": (
            "从 page_math_dataset（MathWriting normalizedLabel 标注的合成版面）导入的单公式真值。"
            "按唯一 latex 去重后导入，不是按页计。"
        ),
        "review_status": "ground_truth_from_mathwriting_normalized_label",
        "review_status_meaning": (
            "真值来自 MathWriting 官方人工标注的 normalizedLabel，不是模型生成，"
            "因此可以直接用于准确率评估（与整页草稿不同，那边必须人工确认）。"
        ),
        "provenance": {
            "dataset": "page_math_dataset.zip",
            "underlying": "MathWriting (CC BY-NC-SA 4.0)",
            "page_count": len(annotations),
            "unique_expressions": len(unique),
            "imported_samples": len(samples),
            "skipped_too_short": skipped_short,
            "note": "100 页只含 370 条唯一 latex，页面是这些公式的重复排版组合。",
        },
        "sample_count": len(samples),
        "samples": samples,
    }
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入 page_math_dataset 为单公式真值清单")
    parser.add_argument("--zip", required=True, help="page_math_dataset.zip 路径")
    parser.add_argument("--output", default=str(_ROOT / "data"), help="输出目录")
    parser.add_argument("--prefix", default="page_math_dataset/", help="zip 内前缀")
    args = parser.parse_args(argv)

    out_dir = Path(args.output)
    with zipfile.ZipFile(args.zip) as zf:
        manifest = build_manifest(zf, args.prefix, out_dir)

    target = out_dir / "page_math_ground_truth.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"页数：{manifest['provenance']['page_count']}")
    print(f"唯一公式数：{manifest['provenance']['unique_expressions']}")
    print(f"导入样本数：{manifest['sample_count']}（跳过过短 {manifest['provenance']['skipped_too_short']} 条）")
    print(f"清单写入：{target}")

    # 顺带算一下图片体积，方便判断要不要进发行包
    total = sum((out_dir / "page_math" / f"{s['sample_id']}.png").stat().st_size for s in manifest["samples"])
    print(f"裁切图总量：{total / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
