"""打包 zip 的文件名编码回归测试。

背景：PowerShell 5.1 的 Compress-Archive 走 .NET Framework，写出来的条目名用反斜杠分隔
（zip 规范要求正斜杠），不认 UTF-8 标志位的解压工具会把中文名处理成乱码，
用户连"哪个是启动脚本"都找不到。scripts/make_package_zip.py 是替代品，这里锁住它的行为。
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_package_zip.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("make_package_zip", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MakePackageZipTests(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()
        self.tmp = Path(tempfile.mkdtemp(prefix="h2l_zip_test_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.staging = self.tmp / "Hand2LaTeX-9.9.9-win64"
        (self.staging / "子目录").mkdir(parents=True)
        for name in ("启动工作台.bat", "关闭工作台.bat", "start.bat", "stop.bat"):
            (self.staging / name).write_text("@echo off\r\n", encoding="ascii")
        (self.staging / "安装说明.txt").write_text("说明", encoding="utf-8")
        (self.staging / "INSTALL.txt").write_text("notes", encoding="utf-8")
        (self.staging / "子目录" / "中文文件.tex").write_text("x", encoding="utf-8")
        self.out = self.tmp / "out.zip"

    def test_zip_uses_forward_slashes_and_utf8_flag(self):
        count = self.module.build_zip(self.staging, self.out)
        self.assertEqual(count, 7)
        report = self.module.audit_zip(self.out, self.staging.name)
        self.assertEqual(report["problems"], [])
        self.assertTrue(report["no_backslash_separators"])
        self.assertTrue(report["non_ascii_all_flagged_utf8"])
        self.assertTrue(report["required_names_present"])

        with zipfile.ZipFile(self.out) as archive:
            infos = archive.infolist()
            self.assertTrue(all("\\" not in info.filename for info in infos))
            non_ascii = [info for info in infos if not info.filename.isascii()]
            self.assertTrue(non_ascii)
            self.assertTrue(all(info.flag_bits & 0x800 for info in non_ascii))
            names = set(archive.namelist())
        top = self.staging.name
        for expected in ("启动工作台.bat", "关闭工作台.bat", "安装说明.txt", "start.bat", "stop.bat", "INSTALL.txt"):
            self.assertIn(f"{top}/{expected}", names)
        self.assertIn(f"{top}/子目录/中文文件.tex", names)

    def test_audit_flags_backslash_names_and_missing_entry(self):
        # 直接喂假条目名：Python 的 zipfile 在 Windows 上会把反斜杠规范化掉，
        # 造不出真实的"坏包"，所以核对逻辑拆成了可以单独喂数据的 audit_names。
        top = self.staging.name
        report = self.module.audit_names(
            top,
            [(f"{top}\\启动工作台.bat", 0x800), (f"{top}/start.bat", 0)],
        )
        self.assertFalse(report["no_backslash_separators"])
        self.assertFalse(report["required_names_present"])
        self.assertTrue(any("反斜杠" in problem for problem in report["problems"]))
        self.assertTrue(any("缺少必须的入口文件" in problem for problem in report["problems"]))

    def test_audit_flags_missing_utf8_flag(self):
        top = self.staging.name
        entries = [(f"{top}/{name}", 0) for name in self.module.REQUIRED_NAMES]
        entries.append((f"{top}/安装说明.txt", 0))
        report = self.module.audit_names(top, entries)
        self.assertFalse(report["non_ascii_all_flagged_utf8"])
        self.assertTrue(any("UTF-8 标志位" in problem for problem in report["problems"]))

    def test_command_line_reports_json_and_exit_code(self):
        completed = subprocess.run(
            [sys.executable, str(_SCRIPT), str(self.staging), str(self.out)],
            capture_output=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout.strip())
        self.assertTrue(report["ok"])
        self.assertEqual(report["files_written"], 7)
        self.assertEqual(report["problems"], [])


if __name__ == "__main__":
    unittest.main()
