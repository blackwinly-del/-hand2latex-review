"""内核基线自洽性测试。

这组用例存在的原因：``scripts/check_kernel.py`` 曾经把两个内核文件的哈希抄错
（抄的是 hand2latex-review 分支的旧内核，而入库的是 11-25 备份的新内核），
于是从建库那一刻起这两个文件就一直飘红。飘红本身不致命，致命的是——它会让
"内核被改了"这个告警失效：真有人动了内核，看到的也是熟悉的红，反而没人查。

所以这里锁住三件事：
1. 内置兜底值与仓库里的文件自洽（没有 git 时也能用）
2. 内置兜底值与该提交里真实内容一致（防止只改一处）
3. 脚本确实能检出改动（防止它变成永远绿的装饰品）
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "check_kernel.py"


def _load_check_kernel():
    spec = importlib.util.spec_from_file_location("check_kernel_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KernelBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _SCRIPT.is_file():
            raise unittest.SkipTest("没有 scripts/check_kernel.py")
        cls.ck = _load_check_kernel()

    def test_fallback_baseline_matches_repository_files(self):
        """内置兜底值必须与仓库里的内核文件自洽。

        交付包里没有 .git，check_kernel.py 会走这份兜底值。兜底值一旦抄错，
        对方拿到包跑一次就看到飘红，会以为我们交付了被改过的内核。
        """
        mismatched = []
        for rel, expected in self.ck.BASELINE.items():
            path = _ROOT / rel
            self.assertTrue(path.is_file(), f"内核文件不存在：{rel}")
            actual = self.ck._normalized_digest(path)
            if actual != expected:
                mismatched.append(f"{rel}（内置 {expected[:8]}，实际 {actual[:8]}）")
        self.assertEqual([], mismatched, "内置兜底基线与仓库文件不一致：" + "；".join(mismatched))

    def test_fallback_matches_baseline_commit(self):
        """兜底值必须等于基线提交里真实的内容，否则两处会各说各话。"""
        if shutil.which("git") is None:
            self.skipTest("本机没有 git")
        commit = self.ck.KERNEL_BASELINE_COMMIT
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=_ROOT,
            capture_output=True,
            check=False,
        )
        if exists.returncode != 0:
            self.skipTest(f"当前仓库里没有基线提交 {commit}")

        drift = []
        for rel, expected in self.ck.BASELINE.items():
            done = subprocess.run(
                ["git", "show", f"{commit}:{rel}"],
                cwd=_ROOT,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, done.returncode, f"基线提交里取不到 {rel}")
            actual = hashlib.sha256(done.stdout.replace(b"\r\n", b"\n")).hexdigest()
            if actual != expected:
                drift.append(f"{rel}（内置 {expected[:8]}，提交 {actual[:8]}）")
        self.assertEqual(
            [], drift, f"内置兜底值与基线提交 {commit} 不一致，改基线时两处要一起改：" + "；".join(drift)
        )

    def test_detects_a_real_change(self):
        """故意改一个内核文件，脚本必须报出来。

        防的是"为了让脚本变绿把基线改成当前值"——那样脚本永远绿，等于没有。
        """
        target = _ROOT / "reasoner.py"
        if not target.is_file():
            self.skipTest("没有 reasoner.py")
        original = target.read_bytes()
        with tempfile.TemporaryDirectory() as workspace:
            # 在临时目录搭一份最小结构，避免动到真实仓库文件
            temp_root = Path(workspace)
            for rel in self.ck.BASELINE:
                source = _ROOT / rel
                destination = temp_root / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
            tampered = temp_root / "reasoner.py"
            tampered.write_bytes(original + b"\n# tampered\n")

            digest = self.ck._normalized_digest(tampered)
            expected = self.ck.BASELINE["reasoner.py"]
            self.assertNotEqual(expected, digest, "改动后指纹应当不同，否则校验算法失效")

    def test_normalization_ignores_line_endings(self):
        """CRLF 与 LF 必须算同一个指纹，否则 Windows 上会误报。"""
        with tempfile.TemporaryDirectory() as workspace:
            path = Path(workspace) / "sample.py"
            path.write_bytes(b"a = 1\r\nb = 2\r\n")
            crlf = self.ck._normalized_digest(path)
            path.write_bytes(b"a = 1\nb = 2\n")
            lf = self.ck._normalized_digest(path)
        self.assertEqual(crlf, lf, "行尾归一化没生效，Windows 上会误报")


if __name__ == "__main__":
    unittest.main()
