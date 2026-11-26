"""scripts/upload_release.py 的回归：token 不许默认从命令行读。

argv 会留在 shell 历史和进程列表里，任何本机进程都读得到。
scripts/push_via_api.py 早就改成默认读环境变量了，这个脚本当时漏了。
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "upload_release.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("upload_release", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UploadReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()
        cls.source = _SCRIPT.read_text(encoding="utf-8")

    def test_token_is_optional_on_the_command_line(self):
        self.assertNotIn('add_argument("--token", required=True)', self.source)
        self.assertIn('os.environ.get("GITHUB_TOKEN"', self.source)

    def test_refuses_to_run_without_any_token(self):
        """既没有 --token 也没有环境变量时必须在发任何请求之前拒绝。"""
        argv = ["upload_release.py", "--repo", "x/y", "--tag", "v0", "--file", "Z:/不存在的文件.zip"]
        with patch.object(sys, "argv", argv), patch.dict("os.environ", {}, clear=True):
            self.assertEqual(self.module.main(), 2)

    def test_reads_token_from_environment(self):
        """只给环境变量时不应因为缺 token 而退出（文件不存在会在其后以 1 退出，证明已越过 token 检查）。"""
        argv = ["upload_release.py", "--repo", "x/y", "--tag", "v0", "--file", "Z:/不存在的文件.zip"]
        with patch.object(sys, "argv", argv), patch.dict("os.environ", {"GITHUB_TOKEN": "t"}):
            self.assertEqual(self.module.main(), 1)


if __name__ == "__main__":
    unittest.main()
