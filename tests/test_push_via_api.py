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

    # ---- 后补的四个缺口 ----

    def test_can_create_branch_with_post(self):
        """新建分支必须用 POST /git/refs；PATCH 对不存在的引用只会给 422。"""
        self.assertIn("--create-branch", self.source)
        self.assertIn('"POST",\n            f"{_API}/repos/{args.repo}/git/refs"', self.source)
        self.assertIn('"ref": f"refs/heads/{args.branch}"', self.source)

    def test_replays_commit_chain_with_multi_parents(self):
        """逐提交重放并保留多父，否则合并提交会被压平成单亲（拓扑丢失）。"""
        self.assertIn("--reverse", self.source, "要按从旧到新的顺序重放")
        self.assertIn("_local_commit_chain", self.source)
        self.assertIn("_commit_meta", self.source)
        # parents 必须来自真实提交对象，不能写死成 [base_sha]。
        self.assertNotIn('"parents": [base_sha]', self.source)
        self.assertIn('"parents": remote_parents', self.source)
        # 合并提交的父可能不止一个，要能从 commit 对象里读出来。
        self.assertIn('line.startswith("parent ")', self.source)

    def test_refuses_stale_base_without_force(self):
        """远端分支已移动时，用过期 base 推等于把别人的提交当删除抹掉——必须拦住。"""
        self.assertIn("remote_tip", self.source)
        self.assertIn("远端分支已经移到", self.source)
        self.assertIn("merge-base", self.source, "还要校验 head 是 base 的后代")
        self.assertIn("--force", self.source)

    def test_verifies_remote_after_push(self):
        """推完不许自说自话：回头拉远端树与本地逐 blob 比对。"""
        self.assertIn("_verify_remote", self.source)
        self.assertIn("自校验", self.source)

    def test_can_delete_branch(self):
        """删分支要 --delete-branch，并且删后复查确认真没了。"""
        self.assertIn("--delete-branch", self.source)
        self.assertIn('"DELETE"', self.source)
        self.assertIn("_delete_branch", self.source)

    def test_missing_branch_is_not_silently_created(self):
        """分支不存在时默认拒绝，避免打错分支名却"成功"建出一条新分支。"""
        self.assertIn("远端没有分支", self.source)

    def test_commit_meta_reads_real_parents(self):
        """直接跑一遍 _commit_meta，锁住"父提交真读得到"。

        这里踩过一个坑：cat-file 返回 bytes，用 str(raw) 会得到 "b'tree ...'" 这种
        字面量，行首是 "b'parent"，startswith("parent ") 永远匹配不到——
        于是每个提交都被当成无父提交，合并拓扑被静默压平。
        """
        meta = self.module._commit_meta("HEAD")
        self.assertTrue(meta["parents"], "HEAD 应该有父提交（仓库已有多条提交）")
        for parent in meta["parents"]:
            self.assertRegex(parent, r"^[0-9a-f]{40}$")

    def test_commit_meta_detects_merge_commits(self):
        """合并提交必须能读出两个父提交。"""
        merges = [
            line.split()[0]
            for line in __import__("subprocess")
            .run(
                ["git", "log", "--merges", "--format=%H", "-20"],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            .stdout.splitlines()
            if line.strip()
        ]
        if not merges:
            self.skipTest("仓库里没有合并提交")
        meta = self.module._commit_meta(merges[0])
        self.assertEqual(len(meta["parents"]), 2, f"{merges[0][:8]} 应该是双亲合并提交")

    def test_resolves_local_stand_in_for_foreign_base(self):
        """远端 base 是本机不认识的 sha 时，要按树哈希找到本地替身。

        不这么做的话，回放第一个提交时会把本地 sha 当父提交去远端查，得到 404。
        （真踩过：base 是上次走 API 推的 3ee41768，本地对应的是 f1cb06b。）
        """
        head_tree = __import__("subprocess").run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        # 拿一个本地绝不存在的假 sha 当"远端 base"，它不可能被 _is_local 认出来。
        fake_remote = "0" * 40
        found = self.module._resolve_local_equivalent(fake_remote, "HEAD", head_tree)
        self.assertEqual(
            found,
            __import__("subprocess")
            .run(["git", "rev-parse", "HEAD"], cwd=_ROOT, capture_output=True, text=True, check=False)
            .stdout.strip(),
            "树与 HEAD 相同的本地提交应该就是 HEAD 自己",
        )

    def test_stand_in_mapping_is_used_for_parents(self):
        """替身映射必须真的进 parents，否则父提交又会变成远端不认识的本地 sha。"""
        self.assertIn("_resolve_local_equivalent", self.source)
        self.assertIn("stand_in_map", self.source)
        self.assertIn("dict(stand_in_map)", self.source)


if __name__ == "__main__":
    unittest.main()
