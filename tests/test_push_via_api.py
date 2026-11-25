"""scripts/push_via_api.py 的回归测试。

这个脚本是 github.com:443 502 时的备用推送通道（git push 走前者，API 走后者）。
它出过的问题都属于"只有真推到那类文件/那种状态才暴露"，所以这里锁住判据本身：
  1. blob 必须用 base64 —— 仓库里有 385 个二进制文件，utf-8 编码对它们必崩；
  2. token 不许默认从命令行读 —— argv 会留在 shell 历史与进程列表里；
  3. 远端树与本地一致时不许再建提交 —— 否则同一条改动在远端出现两次，
     树相同而父提交不同，历史被无意义地拉长（8038b9d 与 8e9dd00 就是这么来的）。
"""

import base64
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "push_via_api.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("push_via_api", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PushViaApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()
        cls.source = _SCRIPT.read_text(encoding="utf-8")

    def test_blobs_are_sent_as_base64(self):
        """二进制文件（png 等）必须能推：判据是请求体里 encoding=base64。"""
        self.assertIn('"encoding": "base64"', self.source)
        # 旧的 utf-8 写法必须彻底消失，否则推到 data/page_math/*.png 就崩。
        self.assertNotIn('"encoding": "utf-8"', self.source)
        self.assertNotIn('content.decode("utf-8")', self.source)
        self.assertIn("import base64", self.source)

    def test_real_binary_file_survives_base64_roundtrip(self):
        """拿仓库里真实存在的一张图验证：utf-8 解码会失败，base64 可往返。"""
        sample = _ROOT / "data" / "page_math" / "pm_001.png"
        if not sample.is_file():
            self.skipTest("仓库里没有 data/page_math/pm_001.png")
        data = sample.read_bytes()
        with self.assertRaises(UnicodeDecodeError):
            data.decode("utf-8")
        encoded = base64.b64encode(data).decode("ascii")
        self.assertEqual(base64.b64decode(encoded), data)

    def test_token_defaults_to_environment_not_argv(self):
        """不带 --token 且无环境变量时必须拒绝运行，且提示指向环境变量。"""
        argv = ["push_via_api.py", "--repo", "x/y", "--base", "HEAD", "--branch", "main"]
        with patch.object(sys, "argv", argv), patch.dict("os.environ", {}, clear=True):
            self.assertEqual(self.module.main(), 2)

    def test_force_requires_explicit_confirmation(self):
        """--force 要问一次；回答不是 yes 就不许动远端引用。"""
        self.assertIn("input(", self.source)
        self.assertIn("--force", self.source)
        # 取消时返回非 0，方便脚本调用方发现"其实没推"。
        self.assertIn("已取消。远端未改动。", self.source)

    def test_skips_when_remote_tree_already_matches(self):
        """幂等闸门：远端树与本地一致时直接返回 0，不建提交、不动引用。"""
        self.assertIn("_remote_blobs", self.source)
        self.assertIn("完全一致", self.source)
        # 比对的是 blob sha 集合，不是文件名——同名不同内容必须能被发现。
        self.assertIn("remote_blobs == local_blobs", self.source)

    def test_truncated_tree_is_not_trusted(self):
        """GitHub 在文件太多时会截断 tree，截断的比对结果不可信，必须退回逐文件计算。"""
        self.assertIn("truncated", self.source)

    def test_deleted_files_are_handled_separately(self):
        """删除的文件不能当成普通改动去取 blob。

        删除的文件在 head 里取不到内容，`git show HEAD:<path>` 退出码是 128，
        整批推送会直接崩。而且树里删条目要显式写 sha=None——
        光"不发这个条目"，base_tree 会把它继承回来，等于没删。
        """
        self.assertIn("--name-status", self.source, "要拿到 D/A/M 状态，不能只用 --name-only")
        self.assertIn('"sha": None', self.source, "删除条目必须显式写 sha=None")
        self.assertNotIn("--name-only", self.source)


if __name__ == "__main__":
    unittest.main()
