import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from workbench.app import (
    _JOBS_ROOT,
    _PROJECT_ROOT,
    _build_info,
    _job_metadata,
    _python_runtime,
    _store_job_metadata,
    _tectonic_status,
    app,
)
from workbench.version import VERSION


# 上传接口现在会按文件头校验真实格式（防止把文本改名成 .png 混过去），
# 所以测试里不能再随手用 b"bytes" 这种假数据。这里给一个 1x1 的合法 PNG，
# 让测试走的是真实调用路径。
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_REST = (
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"  # 宽 1 高 1
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def png(tag: bytes = b"") -> bytes:
    """构造一个签名合法、内容可区分的 PNG。

    内容里带上 tag，是为了让"第 N 页的源图是不是这一张"这类断言仍然能生效
    （原来靠 b"first"/b"second" 区分，现在靠 tag 区分）。
    """
    return _PNG_SIGNATURE + tag + _PNG_REST


class WorkbenchAppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # 这些测试走的是真实接口，落盘位置就是产品在用的 artifacts/jobs。
        # 以前不清理，每跑一次就在用户的侧栏里多出几条「测试笔记」「第一页」。
        # 这里记下开跑前有哪些目录，tearDown 里把新增的删掉——只删自己造的，
        # 别人（或真实使用）建的目录不碰。
        self._jobs_before = self._snapshot_jobs()

    def tearDown(self):
        for name in self._snapshot_jobs() - self._jobs_before:
            shutil.rmtree(_JOBS_ROOT / name, ignore_errors=True)

    @staticmethod
    def _snapshot_jobs() -> set[str]:
        try:
            return {p.name for p in _JOBS_ROOT.iterdir() if p.is_dir()}
        except OSError:
            return set()

    def test_index_loads_local_vue_workbench(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Hand2LaTeX 智能工作台", response.text)
        self.assertIn("/vendor/vue/vue.global.js", response.text)
        self.assertIn("data.detail?.tex", response.text)

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_upload_edit_compile_preview_and_download(self, compile_mock, generate_mock):
        generate_mock.return_value = {
            "title": "测试笔记",
            "blocks": [{"type": "display_formula", "latex": "x^2"}],
            "tex": "\\documentclass{article}\\begin{document}$x^2$\\end{document}\n",
            "model": "test-model",
            "latency_ms": 1,
            "human_review": "required",
            "source_image": "test.png",
        }

        def fake_compile(tex_path):
            Path(tex_path).with_suffix(".pdf").write_bytes(b"%PDF-test")
            return {
                "success": True,
                "pdf_path": str(Path(tex_path).with_suffix(".pdf")),
                "log": "compiled",
                "errors": [],
                "returncode": 0,
            }

        compile_mock.side_effect = fake_compile
        response = self.client.post(
            "/api/documents",
            files={"image": ("note.png", png(), "image/png")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        job_id = data["job_id"]
        self.assertEqual(data["title"], "测试笔记")
        self.assertTrue(data["compile"]["success"])
        self.assertTrue((Path("artifacts/jobs") / job_id / "original.tex").is_file())

        pdf_response = self.client.get(f"/api/jobs/{job_id}/pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.content, b"%PDF-test")

        edited = "\\documentclass{article}\\begin{document}$y^2$\\end{document}\n"
        compile_response = self.client.post(
            f"/api/jobs/{job_id}/compile",
            json={"tex": edited},
        )
        self.assertEqual(compile_response.status_code, 200, compile_response.text)
        self.assertEqual(compile_response.json()["tex"], edited)
        history_files = list((Path("artifacts/jobs") / job_id / "history").glob("*.tex"))
        self.assertGreaterEqual(len(history_files), 2)

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_batch_upload_merges_pages_and_compiles(self, compile_mock, generate_mock):
        generate_mock.side_effect = [
            {
                "title": "第一页",
                "blocks": [{"type": "paragraph", "text": "甲"}],
                "tex": "page one",
                "model": "test-model",
                "latency_ms": 10,
                "human_review": "required",
                "source_image": "p1.png",
            },
            {
                "title": "第二页",
                "blocks": [{"type": "display_formula", "latex": "x^2"}],
                "tex": "page two",
                "model": "test-model",
                "latency_ms": 20,
                "human_review": "required",
                "source_image": "p2.png",
            },
        ]

        def fake_compile(tex_path):
            Path(tex_path).with_suffix(".pdf").write_bytes(b"%PDF-batch")
            return {
                "success": True,
                "pdf_path": str(Path(tex_path).with_suffix(".pdf")),
                "log": "compiled",
                "errors": [],
                "returncode": 0,
            }

        compile_mock.side_effect = fake_compile
        response = self.client.post(
            "/api/documents/batch",
            files=[
                ("image", ("p1.png", png(b"p1"), "image/png")),
                ("image", ("p2.png", png(b"p2"), "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["page_count"], 2)
        self.assertEqual(len(data["pages"]), 2)
        self.assertIn(r"\newpage", data["tex"])
        self.assertIn("x^2", data["tex"])
        self.assertEqual(data["pages"][0]["latency_ms"], 10)
        self.assertEqual(data["pages"][1]["latency_ms"], 20)
        self.assertTrue((Path("artifacts/jobs") / data["job_id"] / "original.tex").is_file())
        self.assertTrue((Path("artifacts/jobs") / data["job_id"] / "page_02" / "original.tex").is_file())
        page_two_source = self.client.get(f"/api/jobs/{data['job_id']}/pages/2/source")
        self.assertEqual(page_two_source.content, png(b"p2"))

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_job_list_reopen_download_and_restore(self, compile_mock, generate_mock):
        generate_mock.return_value = {
            "title": "可恢复笔记",
            "blocks": [{"type": "display_formula", "latex": "x^2"}],
            "tex": "page one",
            "model": "test-model",
            "latency_ms": 1,
            "human_review": "required",
            "source_image": "test.png",
        }

        def fake_compile(tex_path):
            Path(tex_path).with_suffix(".pdf").write_bytes(b"%PDF-test")
            return {
                "success": True,
                "pdf_path": str(Path(tex_path).with_suffix(".pdf")),
                "log": "compiled",
                "errors": [],
                "returncode": 0,
            }

        compile_mock.side_effect = fake_compile
        response = self.client.post(
            "/api/documents",
            files={"image": ("note.png", png(), "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        original = response.json()["tex"]
        job_id = response.json()["job_id"]
        directory = Path("artifacts/jobs") / job_id
        try:
            self.assertTrue((directory / "job.json").is_file())
            self.assertTrue((directory / "compile.json").is_file())

            jobs = self.client.get("/api/jobs").json()["jobs"]
            listed = next(job for job in jobs if job["job_id"] == job_id)
            self.assertEqual(listed["title"], "可恢复笔记")
            self.assertEqual(listed["page_count"], 1)

            reopened = self.client.get(f"/api/jobs/{job_id}")
            self.assertEqual(reopened.status_code, 200, reopened.text)
            data = reopened.json()
            self.assertEqual(data["tex"], original)
            self.assertEqual(data["pages"][0]["merged_page"], 1)
            self.assertTrue(data["compile"]["success"])

            edited = "\\documentclass{article}\\begin{document}$y^2$\\end{document}\n"
            self.client.post(f"/api/jobs/{job_id}/compile", json={"tex": edited})
            self.assertEqual(self.client.get(f"/api/jobs/{job_id}/tex").text.replace("\r\n", "\n"), edited)
            self.assertEqual(self.client.get(f"/api/jobs/{job_id}/original").text.replace("\r\n", "\n"), original)

            restored = self.client.post(f"/api/jobs/{job_id}/restore-original")
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json()["tex"], original)
            self.assertEqual((directory / "main.tex").read_text(encoding="utf-8"), original)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_legacy_job_reopen_reconstructs_pages_and_compile(self):
        directory = Path("artifacts/jobs") / uuid.uuid4().hex
        directory.mkdir(parents=True)
        try:
            tex = "\\title{老任务}\n\\begin{document}\n甲\n\\newpage\n丙\n\\end{document}\n"
            (directory / "main.tex").write_text(tex, encoding="utf-8")
            (directory / "original.tex").write_text(tex, encoding="utf-8")
            (directory / "main.pdf").write_bytes(b"%PDF-old")
            for page, succeeded in ((1, True), (2, False), (3, True)):
                page_directory = directory / f"page_{page:02d}"
                page_directory.mkdir()
                (page_directory / "source.png").write_bytes(png())
                if succeeded:
                    (page_directory / "main.tex").write_text("page", encoding="utf-8")

            response = self.client.get(f"/api/jobs/{directory.name}")

            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["title"], "老任务")
            self.assertEqual(data["page_count"], 2)
            self.assertEqual([page["merged_page"] for page in data["pages"]], [1, None, 2])
            self.assertEqual(data["failed_pages"][0]["page"], 2)
            self.assertTrue(data["compile"]["success"])
            self.assertIn("早于编译记录保存", data["compile"]["log"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_rejects_unsupported_file_type(self):
        response = self.client.post(
            "/api/documents",
            files={"image": ("note.txt", b"text", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)

    def test_fix_requires_confirmation_before_replacing_source(self):
        directory = Path("artifacts/jobs") / uuid.uuid4().hex
        directory.mkdir(parents=True)
        original = "original tex"
        fixed = "fixed tex"
        (directory / "main.tex").write_text(original, encoding="utf-8")
        try:
            with patch("workbench.app.suggest_fix", return_value={"fixed_tex": fixed, "summary": "repair"}):
                response = self.client.post(
                    f"/api/jobs/{directory.name}/suggest-fix",
                    json={"tex": original, "log": "error"},
                )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((directory / "main.tex").read_text(encoding="utf-8"), original)

            (directory / "main.tex").write_text("stale edit", encoding="utf-8")
            stale_response = self.client.post(
                f"/api/jobs/{directory.name}/apply-fix",
                json={"tex": fixed, "summary": "repair"},
            )
            self.assertEqual(stale_response.status_code, 409)
            (directory / "main.tex").write_text(original, encoding="utf-8")

            def fake_compile(tex_path):
                Path(tex_path).with_suffix(".pdf").write_bytes(b"%PDF-fix")
                return {
                    "success": True,
                    "pdf_path": str(Path(tex_path).with_suffix(".pdf")),
                    "log": "fixed",
                    "errors": [],
                    "returncode": 0,
                }

            with patch("workbench.app.compile_tex", side_effect=fake_compile):
                response = self.client.post(
                    f"/api/jobs/{directory.name}/apply-fix",
                    json={"tex": fixed, "summary": "repair"},
                )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((directory / "main.tex").read_text(encoding="utf-8"), fixed)
            self.assertTrue((directory / "fix_applied.json").is_file())
        finally:
            shutil.rmtree(directory)

    def test_apply_compile_exception_returns_current_source(self):
        directory = Path("artifacts/jobs") / uuid.uuid4().hex
        directory.mkdir(parents=True)
        original = "original tex"
        fixed = "fixed tex"
        (directory / "main.tex").write_text(original, encoding="utf-8")
        try:
            with patch("workbench.app.suggest_fix", return_value={"fixed_tex": fixed, "summary": "repair"}):
                self.client.post(
                    f"/api/jobs/{directory.name}/suggest-fix",
                    json={"tex": original, "log": "error"},
                )
            with patch("workbench.app.compile_tex", side_effect=RuntimeError("boom")):
                response = self.client.post(
                    f"/api/jobs/{directory.name}/apply-fix",
                    json={"tex": fixed, "summary": "repair"},
                )

            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["detail"]["tex"], fixed)
            self.assertEqual((directory / "main.tex").read_text(encoding="utf-8"), fixed)
            self.assertTrue((directory / "fix_applied.json").is_file())
        finally:
            shutil.rmtree(directory)

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_batch_upload_partial_failure_keeps_successful_pages(self, compile_mock, generate_mock):
        generate_mock.side_effect = [
            {
                "title": "第一页",
                "blocks": [{"type": "paragraph", "text": "甲"}],
                "tex": "page one",
                "model": "test-model",
                "latency_ms": 10,
                "human_review": "required",
                "source_image": "p1.png",
            },
            RuntimeError("page two exploded"),
            {
                "title": "第三页",
                "blocks": [{"type": "paragraph", "text": "丙"}],
                "tex": "page three",
                "model": "test-model",
                "latency_ms": 30,
                "human_review": "required",
                "source_image": "p3.png",
            },
        ]

        def fake_compile(tex_path):
            Path(tex_path).with_suffix(".pdf").write_bytes(b"%PDF-partial")
            return {
                "success": True,
                "pdf_path": str(Path(tex_path).with_suffix(".pdf")),
                "log": "compiled",
                "errors": [],
                "returncode": 0,
            }

        compile_mock.side_effect = fake_compile
        response = self.client.post(
            "/api/documents/batch",
            files=[
                ("image", ("p1.png", png(b"p1"), "image/png")),
                ("image", ("p2.png", png(b"p2"), "image/png")),
                ("image", ("p3.png", png(b"p3"), "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        job_id = data["job_id"]
        # 成功页进入文档；失败页不进入
        self.assertEqual(data["page_count"], 2)
        self.assertIn("甲", data["tex"])
        self.assertIn("丙", data["tex"])
        self.assertNotIn("乙", data["tex"])
        # pages 覆盖全部三页（失败页带 error），failed_pages 指明第 2 页
        self.assertEqual(len(data["pages"]), 3)
        self.assertEqual(data["pages"][1]["error"], "RuntimeError: page two exploded")
        self.assertIsNone(data["pages"][0]["error"])
        self.assertEqual(data["failed_pages"], [{"page": 2, "error": "RuntimeError: page two exploded"}])
        self.assertEqual([page["merged_page"] for page in data["pages"]], [1, None, 2])
        # 源图三个目录都在（失败页的原图也保留），失败页没有 original.tex
        self.assertTrue((Path("artifacts/jobs") / job_id / "page_01" / "original.tex").is_file())
        self.assertFalse((Path("artifacts/jobs") / job_id / "page_02" / "original.tex").exists())
        self.assertTrue((Path("artifacts/jobs") / job_id / "page_03" / "original.tex").is_file())
        page_two_source = self.client.get(f"/api/jobs/{job_id}/pages/2/source")
        self.assertEqual(page_two_source.content, png(b"p2"))
        self.assertTrue(data["compile"]["success"])

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_retry_failed_page_reuses_successful_pages(self, compile_mock, generate_mock):
        def document(title, text, latency):
            return {
                "title": title,
                "blocks": [{"type": "paragraph", "text": text}],
                "tex": text,
                "model": "test-model",
                "latency_ms": latency,
                "human_review": "required",
                "source_image": "test.png",
            }

        generate_mock.side_effect = [
            document("第一页", "甲", 10),
            RuntimeError("page two exploded"),
            document("第三页", "丙", 30),
            document("第二页", "乙", 20),
        ]

        def fake_compile(tex_path):
            Path(tex_path).with_suffix(".pdf").write_bytes(b"%PDF-retry")
            return {
                "success": True,
                "pdf_path": str(Path(tex_path).with_suffix(".pdf")),
                "log": "compiled",
                "errors": [],
                "returncode": 0,
            }

        compile_mock.side_effect = fake_compile
        response = self.client.post(
            "/api/documents/batch",
            files=[
                ("image", ("p1.png", png(b"p1"), "image/png")),
                ("image", ("p2.png", png(b"p2"), "image/png")),
                ("image", ("p3.png", png(b"p3"), "image/png")),
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["job_id"]
        directory = Path("artifacts/jobs") / job_id
        try:
            retried = self.client.post(f"/api/jobs/{job_id}/pages/2/retry")

            self.assertEqual(retried.status_code, 200, retried.text)
            data = retried.json()
            self.assertEqual(generate_mock.call_count, 4)
            self.assertIn("page_02", generate_mock.call_args.args[0])
            self.assertEqual(data["page_count"], 3)
            self.assertNotIn("failed_pages", data)
            self.assertEqual([page["merged_page"] for page in data["pages"]], [1, 2, 3])
            self.assertIsNone(data["pages"][1]["error"])
            self.assertEqual(data["pages"][1]["latency_ms"], 20)
            self.assertIn("乙", data["tex"])
            self.assertLess(data["tex"].index("甲"), data["tex"].index("乙"))
            self.assertLess(data["tex"].index("乙"), data["tex"].index("丙"))

            again = self.client.post(f"/api/jobs/{job_id}/pages/2/retry")
            self.assertEqual(again.status_code, 409)
            self.assertEqual(generate_mock.call_count, 4)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_batch_upload_all_pages_fail_returns_422_and_cleans_up(self, compile_mock, generate_mock):
        """所有页都失败时：返回 422（不是 502），并且不留下空任务目录。

        502 表示"服务端配置坏了"，422 表示"这次上传本身不成立"。
        全部页识别失败属于后者——把它报成 502 会把人引去查密钥和编译器。
        同时目录必须清掉：以前这里会留一个只有源图、没有 main.tex 的孤儿目录。
        """
        before = {p.name for p in (Path("artifacts/jobs")).iterdir() if p.is_dir()}
        generate_mock.side_effect = [RuntimeError("first down"), RuntimeError("second down")]

        response = self.client.post(
            "/api/documents/batch",
            files=[
                ("image", ("p1.png", png(b"p1"), "image/png")),
                ("image", ("p2.png", png(b"p2"), "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 422, response.text)
        # 逐页原因要能读到，不能只给一句笼统的话
        self.assertIn("第 1 页", response.text)
        self.assertIn("first down", response.text)
        compile_mock.assert_not_called()

        after = {p.name for p in (Path("artifacts/jobs")).iterdir() if p.is_dir()}
        self.assertEqual(after, before, "失败的整批上传不应该留下任务目录")

    def test_cleanup_expired_jobs_removes_only_stale_directories(self):
        from workbench.app import _cleanup_expired_jobs

        fresh = Path("artifacts/jobs") / uuid.uuid4().hex
        stale = Path("artifacts/jobs") / uuid.uuid4().hex
        fresh.mkdir(parents=True)
        stale.mkdir(parents=True)
        old_timestamp = time.time() - 8 * 86400
        os.utime(stale, (old_timestamp, old_timestamp))
        try:
            removed = _cleanup_expired_jobs(max_age_seconds=7 * 86400)

            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertGreaterEqual(removed, 1)
        finally:
            shutil.rmtree(fresh, ignore_errors=True)
            shutil.rmtree(stale, ignore_errors=True)

    def test_cleanup_ignores_non_job_entries(self):
        from workbench.app import _cleanup_expired_jobs

        stranger = Path("artifacts/jobs") / "not-a-job-id.txt"
        stranger.write_text("keep me", encoding="utf-8")
        old_timestamp = time.time() - 30 * 86400
        os.utime(stranger, (old_timestamp, old_timestamp))
        try:
            _cleanup_expired_jobs(max_age_seconds=7 * 86400)

            self.assertTrue(stranger.exists())
        finally:
            stranger.unlink(missing_ok=True)

    def test_job_metadata_does_not_recompute_has_figures_when_present(self):
        """job.json 已写 has_figures 时，不该再去扫 page_*/document.json。

        以前是 metadata.setdefault("has_figures", _has_figure_blocks(directory))。
        setdefault 的默认值参数是**先求值再传进去**的，键已存在也照样算——
        也就是说每个任务列表请求都把「所有任务的 pages 全 glob + 解析一遍」做了一次。
        实测 300 个任务时 /api/jobs 要 2.2 秒，这一行占 61%。

        这里用打桩来固定行为：只要键存在，_has_figure_blocks 就不该被调用。
        """
        directory = Path("artifacts/jobs") / uuid.uuid4().hex
        directory.mkdir(parents=True)
        try:
            (directory / "main.tex").write_text("content", encoding="utf-8")
            (directory / "job.json").write_text(
                json.dumps({"title": "已有元数据", "page_count": 1, "pages": [], "has_figures": False}),
                encoding="utf-8",
            )
            with patch("workbench.app._has_figure_blocks") as has_figures:
                metadata = _job_metadata(directory)
            has_figures.assert_not_called()
            self.assertFalse(metadata["has_figures"])
            self.assertEqual(metadata["title"], "已有元数据")

            # 键缺失时仍然要算：老任务没有这个字段，不能默认成 False 就算完。
            (directory / "job.json").write_text(
                json.dumps({"title": "老任务"}, ensure_ascii=False), encoding="utf-8"
            )
            with patch("workbench.app._has_figure_blocks", return_value=True) as has_figures:
                metadata = _job_metadata(directory)
            has_figures.assert_called_once()
            self.assertTrue(metadata["has_figures"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_review_state_is_persisted_to_job_json(self):
        """核对进度必须存在服务端，不能只活在浏览器里。

        原先只有 localStorage：换机器、换浏览器、清缓存就全没了，而且没有提示。
        做多页笔记的人是"今天核 8 页、明天续"，进度的寿命不该比任务还短。
        """
        job_id = uuid.uuid4().hex
        directory = _JOBS_ROOT / job_id
        directory.mkdir(parents=True)
        (directory / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nx\n\\end{document}", encoding="utf-8")
        (directory / "job.json").write_text(
            json.dumps({"title": "多页笔记", "page_count": 3, "pages": [], "has_figures": False}),
            encoding="utf-8",
        )

        response = self.client.post(f"/api/jobs/{job_id}/review", json={"pages": {"1": True, "2": True}})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["reviewed_count"], 2)
        self.assertEqual(body["changed"], 2)

        stored = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["reviewed_pages"], {"1": True, "2": True})
        self.assertIn("reviewed_updated_at", stored)

        # 取消勾选要把键删掉，而不是留一个 false——
        # 这样 job.json 里只看键就知道核到第几页，也不会随页数无限增长。
        response = self.client.post(f"/api/jobs/{job_id}/review", json={"pages": {"2": False}})
        self.assertEqual(response.status_code, 200, response.text)
        stored = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["reviewed_pages"], {"1": True})

        # 打开任务时要把进度一起带回来，前端才不用额外发请求
        detail = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["reviewed_pages"], {"1": True})

    def test_review_rejects_page_out_of_range(self):
        """页号超出实际页数说明前端状态串了，不能悄悄写进 job.json。"""
        job_id = uuid.uuid4().hex
        directory = _JOBS_ROOT / job_id
        directory.mkdir(parents=True)
        (directory / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nx\n\\end{document}", encoding="utf-8")
        (directory / "job.json").write_text(
            json.dumps({"title": "两页", "page_count": 2, "pages": [], "has_figures": False}),
            encoding="utf-8",
        )
        response = self.client.post(f"/api/jobs/{job_id}/review", json={"pages": {"9": True}})
        self.assertEqual(response.status_code, 400)
        stored = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(stored.get("reviewed_pages"), None)

    def test_review_survives_metadata_rewrite(self):
        """重试单页 / 图形页换原图会整份重写 job.json，进度不能被抹掉。

        用户核对到第 8 页、去重试一个失败页，回来发现对勾全没了——
        这比"没保存"更让人恼火。
        """
        job_id = uuid.uuid4().hex
        directory = _JOBS_ROOT / job_id
        directory.mkdir(parents=True)
        (directory / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nx\n\\end{document}", encoding="utf-8")
        (directory / "job.json").write_text(
            json.dumps({
                "title": "续核", "page_count": 3, "pages": [], "has_figures": False,
                "reviewed_pages": {"1": True, "2": True},
                "reviewed_updated_at": "2026-01-01T00:00:00+00:00",
            }),
            encoding="utf-8",
        )
        _store_job_metadata(directory, "续核", 3, [{"page": 1}], [], has_figures=False)
        stored = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["reviewed_pages"], {"1": True, "2": True})
        self.assertEqual(stored["reviewed_updated_at"], "2026-01-01T00:00:00+00:00")

    def test_review_on_missing_job_returns_404(self):
        response = self.client.post(f"/api/jobs/{uuid.uuid4().hex}/review", json={"pages": {"1": True}})
        self.assertEqual(response.status_code, 404)

    def test_compile_payload_exposes_diagnostics(self):
        """compile 接口要带上结构化诊断，前端才有行号和上下文可用。"""
        job_id = uuid.uuid4().hex
        directory = _JOBS_ROOT / job_id
        directory.mkdir(parents=True)
        (directory / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nx\n\\end{document}", encoding="utf-8")
        (directory / "job.json").write_text(
            json.dumps({"title": "诊断", "page_count": 1, "pages": [], "has_figures": False}),
            encoding="utf-8",
        )
        detail = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("diagnostics", detail.json()["compile"])

    def test_job_list_supports_search_and_pagination(self):
        # 标题里带本次运行唯一的标记。固定标题（"分页验收A/B"）有个坑：tearDown 的
        # shutil.rmtree 一旦被打断（例如被批量删除守卫 SystemExit 掉），旧夹具就永久留在
        # artifacts/jobs 里，下次运行的 total 会从 2 变成 4 或 8。按唯一标记查询，
        # 测试就和被污染的 artifacts/jobs 彻底解耦，不依赖清理一定跑完。
        marker = uuid.uuid4().hex[:8]
        needle = f"分页验收-{marker}"
        directories = []
        try:
            for index, title in enumerate((f"{needle}-A", f"{needle}-B", f"其他任务-{marker}")):
                directory = Path("artifacts/jobs") / uuid.uuid4().hex
                directory.mkdir(parents=True)
                directories.append(directory)
                (directory / "main.tex").write_text("content", encoding="utf-8")
                (directory / "job.json").write_text(
                    json.dumps({"title": title, "page_count": 1, "pages": []}, ensure_ascii=False),
                    encoding="utf-8",
                )
                timestamp = time.time() - index * 10
                os.utime(directory, (timestamp, timestamp))

            first = self.client.get("/api/jobs", params={"q": needle, "limit": 1, "offset": 0})
            second = self.client.get("/api/jobs", params={"q": needle, "limit": 1, "offset": 1})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["total"], 2)
            self.assertEqual(second.json()["total"], 2)
            self.assertEqual(len(first.json()["jobs"]), 1)
            self.assertEqual(len(second.json()["jobs"]), 1)
            self.assertNotEqual(first.json()["jobs"][0]["job_id"], second.json()["jobs"][0]["job_id"])

            by_id = self.client.get("/api/jobs", params={"q": directories[0].name[:12]})
            self.assertEqual(by_id.json()["total"], 1)
            self.assertEqual(by_id.json()["jobs"][0]["job_id"], directories[0].name)

            missing = self.client.get("/api/jobs", params={"q": "不存在的标题"})
            self.assertEqual(missing.json()["total"], 0)
            self.assertEqual(missing.json()["jobs"], [])
        finally:
            for directory in directories:
                shutil.rmtree(directory, ignore_errors=True)

    def test_job_list_reads_metadata_only_for_current_page(self):
        """列表页只该为「当前这一页」读元数据，不是为全部任务读。

        这条测的是性能优化的**行为边界**，不是速度本身（计时断言在 CI 上必然抖）。
        做法：给一批任务写好 job.json 之后，把 `_job_metadata` 换成会计数的包装，
        断言「不限搜索、limit=2」时它的调用次数就等于 2，而不是任务总数。

        只要有人把它改回"先全量读元数据再切片"，这条就会红。这个回归很容易
        悄悄发生——两种写法返回的结果一模一样，只有调用次数不同。
        """
        import workbench.app as workbench_app

        directories = []
        try:
            for index in range(6):
                directory = Path("artifacts/jobs") / uuid.uuid4().hex
                directory.mkdir(parents=True)
                directories.append(directory)
                (directory / "main.tex").write_text("content", encoding="utf-8")
                (directory / "job.json").write_text(
                    json.dumps({"title": f"懒读验收{index}", "page_count": 1, "pages": []},
                               ensure_ascii=False),
                    encoding="utf-8",
                )
                timestamp = time.time() - index * 10
                os.utime(directory, (timestamp, timestamp))

            calls = []
            real = workbench_app._job_metadata

            def counting(entry):
                calls.append(entry.name)
                return real(entry)

            with patch.object(workbench_app, "_job_metadata", counting):
                response = self.client.get("/api/jobs", params={"limit": 2})
                self.assertEqual(response.status_code, 200, response.text)
                page_calls = len(calls)
                self.assertEqual(len(response.json()["jobs"]), 2)

                # 同一个请求里只该读 2 次；把全部 6 个都读了就是没懒起来。
                self.assertEqual(
                    page_calls, 2,
                    f"limit=2 却读了 {page_calls} 次元数据，说明又退回全量读了",
                )

                # 有搜索词时必须全量读——不读就判断不了命中。这条防止有人
                # 为了"更快"把搜索也改成只读当前页，那会漏结果。
                calls.clear()
                searched = self.client.get("/api/jobs", params={"q": "懒读验收", "limit": 2})
                self.assertEqual(searched.status_code, 200, searched.text)
                self.assertGreater(
                    len(calls), 2,
                    "搜索路径也懒读了，会漏掉不在当前页的命中项",
                )
                self.assertGreaterEqual(searched.json()["total"], 2)
        finally:
            for directory in directories:
                shutil.rmtree(directory, ignore_errors=True)

    def test_directory_usage_counts_nested_files_and_skips_non_jobs(self):
        """目录统计要数到多层子目录，且不把非任务目录算进去。

        这条锁的是 `_directory_usage` 替换 `Path.rglob("*")` 之后的行为等价性。
        换实现是为了性能（72 任务实测 125ms → 48ms），但"更快"不能以"数错"为代价：
        rglob 会递归到底，手写 scandir 如果只扫一层就会少算 page_*/ 里的大文件，
        而那个数字会显示在状态面板上，少了也没人看得出来。
        """
        import workbench.app as workbench_app

        root = Path(tempfile.mkdtemp(prefix="usage_"))
        job = root / uuid.uuid4().hex
        try:
            (job / "page_01" / "deeper").mkdir(parents=True)
            (job / "main.tex").write_bytes(b"x" * 10)
            (job / "page_01" / "source.png").write_bytes(b"y" * 100)
            # 第三层：只有递归到底才会被数到，漏了它就是少算 1000 字节。
            (job / "page_01" / "deeper" / "main.pdf").write_bytes(b"z" * 1000)
            # 非任务目录（名字不符合 job_id 格式）不该被计入任务数。
            (root / "not-a-job").mkdir()
            (root / "not-a-job" / "big.bin").write_bytes(b"w" * 5000)

            count, total = workbench_app._directory_usage(root)
            self.assertEqual(count, 1, "非任务目录被当成任务计入了")
            self.assertEqual(total, 10 + 100 + 1000, "多层子目录没有被数全")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_directory_usage_survives_missing_root(self):
        """目录不存在时返回 (0, 0)，不抛异常。

        状态接口因为一个不存在或没权限的目录整条 500 不划算，前端只是拿它
        显示一个体积数字。
        """
        import workbench.app as workbench_app

        count, total = workbench_app._directory_usage(Path(tempfile.gettempdir()) / "definitely-absent-xyz")
        self.assertEqual((count, total), (0, 0))

    def test_job_list_survives_corrupt_job_json(self):
        """一个写坏的 job.json 不能让整张任务列表 500。

        这不是假想：写 job.json 时进程被杀、磁盘写满，都会留下截断的 JSON。
        原来的 `_job_metadata` 直接 json.loads，一条坏数据抛 JSONDecodeError，
        /api/jobs 整条接口 500 —— 用户看到的是"任务全没了"，而不是"某个任务坏了"。
        现在走 `_read_job_json`：读不出来就按目录结构重建，标题从 main.tex 里取。
        """
        import workbench.app as workbench_app

        root = Path(tempfile.mkdtemp(prefix="corrupt_"))
        broken = root / (uuid.uuid4().hex)
        healthy = root / (uuid.uuid4().hex)
        original = workbench_app._JOBS_ROOT
        try:
            broken.mkdir()
            (broken / "main.tex").write_text("\\title{坏掉的任务}\n", encoding="utf-8")
            (broken / "job.json").write_text('{"title": "半截', encoding="utf-8")
            (broken / "page_01").mkdir()
            (broken / "page_01" / "source.png").write_bytes(png())

            healthy.mkdir()
            (healthy / "main.tex").write_text("x", encoding="utf-8")
            (healthy / "job.json").write_text(
                json.dumps({"title": "正常任务", "page_count": 1, "pages": [], "has_figures": False}),
                encoding="utf-8",
            )
            (healthy / "page_01").mkdir()
            (healthy / "page_01" / "source.png").write_bytes(png())

            workbench_app._JOBS_ROOT = root
            # 顺带把"留下痕迹"也锁住：重建成功不能把损坏掩盖得无声无息，
            # 否则下次排查只会看到标题变成了默认值，找不到原因。
            with self.assertLogs("workbench", level="WARNING") as captured:
                result = workbench_app.list_jobs(limit=20)
        finally:
            workbench_app._JOBS_ROOT = original
            shutil.rmtree(root, ignore_errors=True)

        self.assertIn("job.json", "\n".join(captured.output), "job.json 损坏没有留下日志")
        titles = sorted(job["title"] for job in result["jobs"])
        self.assertEqual(titles, ["坏掉的任务", "正常任务"], "坏掉的 job.json 把正常任务也一起拖没了")
        self.assertEqual(result["total"], 2)

    def test_job_list_survives_non_utf8_title_file(self):
        """main.tex 不是 UTF-8 也不能让列表 500。

        外来文件（GBK 存的 .tex）和被中断的写入都会产生这种文件。原来
        `_read_job_title` 里裸调 read_text，一个字节不对就是 UnicodeDecodeError，
        同样是整条接口倒掉。现在跳过该文件、退回默认标题。
        """
        import workbench.app as workbench_app

        root = Path(tempfile.mkdtemp(prefix="badenc_"))
        job = root / uuid.uuid4().hex
        original = workbench_app._JOBS_ROOT
        try:
            job.mkdir()
            # 合法 UTF-8 的 title 行 + 一段非法字节：读的时候必然解码失败。
            (job / "main.tex").write_bytes(b"\\title{\xd6\xd0\xce\xc4}\n")
            (job / "page_01").mkdir()
            (job / "page_01" / "source.png").write_bytes(png())

            workbench_app._JOBS_ROOT = root
            with self.assertLogs("workbench", level="WARNING") as captured:
                result = workbench_app.list_jobs(limit=20)
        finally:
            workbench_app._JOBS_ROOT = original
            shutil.rmtree(root, ignore_errors=True)

        self.assertIn("标题文件", "\n".join(captured.output), "非 UTF-8 的 .tex 被静默跳过了")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["jobs"][0]["title"], "手写笔记")

    def test_has_figure_blocks_ignores_non_dict_document(self):
        """document.json 顶层不是对象时，`document.get` 不能把列表接口打挂。

        `_has_figure_blocks` 原本只防了 JSONDecodeError，没防"合法 JSON 但类型不对"：
        顶层是数组时 `document.get("blocks")` 抛 AttributeError。
        """
        import workbench.app as workbench_app

        root = Path(tempfile.mkdtemp(prefix="baddoc_"))
        original = workbench_app._JOBS_ROOT
        try:
            for payload, expected in (("[]", False), ('{"blocks": "not-a-list"}', False), ('{"blocks": [{"type": "figure"}]}', True)):
                job = root / uuid.uuid4().hex
                (job / "page_01").mkdir(parents=True)
                (job / "main.tex").write_text("x", encoding="utf-8")
                (job / "page_01" / "document.json").write_text(payload, encoding="utf-8")
                self.assertEqual(
                    workbench_app._has_figure_blocks(job), expected, "document.json=%s 判定错了" % payload
                )
        finally:
            workbench_app._JOBS_ROOT = original
            shutil.rmtree(root, ignore_errors=True)

    @patch("workbench.app.compile_tex")
    def test_stored_compile_survives_corrupt_record(self, compile_mock):
        """截断的 compile.json 不能让"打开任务"整条 500。

        compile.json 用 write_text 写出，不是原子写：编译时进程被杀或磁盘写满会
        留下半截 JSON。以前 GET /api/jobs/{id} 会直接抛 JSONDecodeError。
        现在按"没有编译记录"处理 —— 有 PDF 就照常打开，没有就重编一次。
        """
        import workbench.app as workbench_app

        compile_mock.return_value = {
            "success": False,
            "log": "重编后的日志",
            "errors": ["boom"],
            "returncode": 1,
            "diagnostics": [],
        }
        root = Path(tempfile.mkdtemp(prefix="badcompile_"))
        with_pdf = root / uuid.uuid4().hex
        without_pdf = root / uuid.uuid4().hex
        try:
            for job in (with_pdf, without_pdf):
                job.mkdir()
                (job / "main.tex").write_text("x", encoding="utf-8")
                (job / "compile.json").write_text('{"success": tr', encoding="utf-8")
            (with_pdf / "main.pdf").write_bytes(b"%PDF-1.4")

            with self.assertLogs("workbench", level="WARNING"):
                stored = workbench_app._stored_compile(with_pdf, with_pdf.name)
                recompiled = workbench_app._stored_compile(without_pdf, without_pdf.name)
        finally:
            shutil.rmtree(root, ignore_errors=True)

        # 有 PDF：不为了打开任务再跑一遍编译，但要如实说明日志缺失。
        self.assertTrue(stored["success"])
        self.assertIn("未重新编译", stored["log"])
        compile_mock.assert_called_once()
        # 没有 PDF：必须真的重编，否则打开任务是一片空白且没有原因。
        self.assertEqual(recompiled["log"], "重编后的日志")
        self.assertEqual(recompiled["errors"], ["boom"])

    def test_apply_fix_rejects_corrupt_suggestion_with_409(self):
        """损坏的 suggestion.json 返回 409 而不是 500，且不能把源码写坏。

        `suggestion.json` 也是 write_text 写出来的非原子写。以前直接 json.loads，
        应用修复时会抛 JSONDecodeError 变 500，用户不知道该怎么办；而这一步本来
        就有"重新生成建议"这个出口，用 409 说清楚才有用。
        """
        directory = Path("artifacts/jobs") / uuid.uuid4().hex
        directory.mkdir(parents=True)
        try:
            (directory / "main.tex").write_text("原始内容", encoding="utf-8")
            (directory / "suggestion.json").write_text('{"summary": "半截', encoding="utf-8")

            response = TestClient(app).post(
                f"/api/jobs/{directory.name}/apply-fix",
                json={"tex": "新内容", "summary": "改动"},
            )

            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn("损坏", response.json()["detail"])
            # 校验没过就不能动源码——否则用户会拿到一份"改了但没编译"的文件。
            self.assertEqual((directory / "main.tex").read_text(encoding="utf-8"), "原始内容")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    @patch("workbench.app.compile_tex")
    def test_use_source_figures_rebuilds_without_recognition(self, compile_mock):
        directory = Path("artifacts/jobs") / uuid.uuid4().hex
        page_directory = directory / "page_01"
        page_directory.mkdir(parents=True)
        try:
            (page_directory / "source.png").write_bytes(png())
            description = (
                "A flowchart illustrating a psychological model. It shows Social Feedback "
                "and Memory with arrows, plus a legend explaining the relationships."
            )
            document = {
                "title": "图页",
                "blocks": [
                    {"type": "figure", "description": description},
                    {"type": "paragraph", "text": "Social Feedback\n(e.g., acceptance)"},
                    {"type": "paragraph", "text": "Memory\n(e.g., social events)"},
                ],
            }
            (page_directory / "document.json").write_text(
                json.dumps(document, ensure_ascii=False),
                encoding="utf-8",
            )
            placeholder = "\\fbox{原始示意图（未重新绘制）}\n"
            (directory / "main.tex").write_text(placeholder, encoding="utf-8")
            (directory / "original.tex").write_text(placeholder, encoding="utf-8")
            (directory / "job.json").write_text(
                json.dumps({
                    "title": "图页",
                    "page_count": 1,
                    "pages": [{
                        "page": 1,
                        "source_url": f"/api/jobs/{directory.name}/pages/1/source",
                        "latency_ms": 1,
                        "human_review": True,
                        "error": None,
                        "merged_page": 1,
                    }],
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            def fake_compile(tex_path):
                Path(tex_path).with_suffix(".pdf").write_bytes(b"%PDF-figure")
                return {
                    "success": True,
                    "pdf_path": str(Path(tex_path).with_suffix(".pdf")),
                    "log": "compiled",
                    "errors": [],
                    "returncode": 0,
                }

            compile_mock.side_effect = fake_compile
            response = self.client.post(f"/api/jobs/{directory.name}/figures/use-source")

            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertTrue(data["has_figures"])
            tex = (directory / "main.tex").read_text(encoding="utf-8")
            self.assertIn(r"\includegraphics", tex)
            self.assertNotIn("原始示意图（未重新绘制）", tex)
            self.assertNotIn("Social Feedback\n(e.g., acceptance)", tex)
            saved_document = json.loads(
                (page_directory / "document.json").read_text(encoding="utf-8")
            )
            self.assertTrue(Path(saved_document["blocks"][0]["source_image"]).is_file())
            compile_mock.assert_called()
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_missing_job_returns_404(self):
        response = self.client.get("/api/jobs/00000000000000000000000000000000/pdf")
        self.assertEqual(response.status_code, 404)

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_pages_are_recognized_in_parallel_and_keep_order(self, compile_mock, generate_mock):
        barrier = threading.Barrier(2, timeout=15)

        def fake_generate(source_path):
            page_number = int(Path(source_path).parent.name.split("_")[1])
            # 两页必须同时到达这里，否则 barrier 超时——这就证明是并行等待的。
            barrier.wait()
            return {
                "title": f"第{page_number}页",
                "blocks": [{"type": "paragraph", "text": f"内容{page_number}"}],
                "tex": f"page {page_number}",
                "model": "test-model",
                "latency_ms": page_number,
                "human_review": "required",
                "source_image": source_path,
                "signals": {"attempts": 1, "retried": False, "block_stats": {"paragraph": 1}},
            }

        generate_mock.side_effect = fake_generate
        compile_mock.side_effect = self._fake_compile
        run_id = uuid.uuid4().hex
        started = time.perf_counter()
        with patch.dict(os.environ, {"WORKBENCH_PAGE_CONCURRENCY": "2"}):
            response = self.client.post(
                "/api/documents/batch",
                files=[
                    ("image", ("p1.png", png(b"p1"), "image/png")),
                    ("image", ("p2.png", png(b"p2"), "image/png")),
                ],
                data={"run_id": run_id},
            )
        elapsed = time.perf_counter() - started

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        directory = Path("artifacts/jobs") / data["job_id"]
        try:
            self.assertEqual(data["run_id"], run_id)
            self.assertEqual([page["page"] for page in data["pages"]], [1, 2])
            self.assertEqual([page["merged_page"] for page in data["pages"]], [1, 2])
            self.assertLess(data["tex"].index("内容1"), data["tex"].index("内容2"))
            self.assertEqual(data["pages"][0]["signals"]["retried"], False)
            self.assertLess(elapsed, 15)

            progress = self.client.get(f"/api/runs/{run_id}")
            self.assertEqual(progress.status_code, 200, progress.text)
            run = progress.json()
            self.assertEqual(run["status"], "done")
            self.assertEqual(run["job_id"], data["job_id"])
            self.assertEqual(run["done_pages"], 2)
            self.assertEqual([page["state"] for page in run["pages"]], ["done", "done"])
            self.assertEqual([page["latency_ms"] for page in run["pages"]], [1, 2])

            stored = json.loads((directory / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["pages"][1]["signals"]["block_stats"]["paragraph"], 1)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def _fake_compile(self, tex_path):
        Path(tex_path).with_suffix(".pdf").write_bytes(b"%PDF-test")
        return {
            "success": True,
            "pdf_path": str(Path(tex_path).with_suffix(".pdf")),
            "log": "compiled",
            "errors": [],
            "returncode": 0,
        }

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_run_progress_records_failed_page(self, compile_mock, generate_mock):
        def fake_generate(source_path):
            page_number = int(Path(source_path).parent.name.split("_")[1])
            if page_number == 2:
                raise RuntimeError("page two exploded")
            return {
                "title": "第一页",
                "blocks": [{"type": "paragraph", "text": "甲"}],
                "tex": "page one",
                "model": "test-model",
                "latency_ms": 5,
                "human_review": "required",
                "source_image": source_path,
                "signals": {"attempts": 1, "retried": False},
            }

        generate_mock.side_effect = fake_generate
        compile_mock.side_effect = self._fake_compile
        run_id = uuid.uuid4().hex
        response = self.client.post(
            "/api/documents/batch",
            files=[
                ("image", ("p1.png", png(b"p1"), "image/png")),
                ("image", ("p2.png", png(b"p2"), "image/png")),
            ],
            data={"run_id": run_id},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        directory = Path("artifacts/jobs") / data["job_id"]
        try:
            self.assertEqual(data["page_count"], 1)
            self.assertEqual(data["pages"][1]["merged_page"], None)
            run = self.client.get(f"/api/runs/{run_id}").json()
            self.assertEqual(run["pages"][0]["state"], "done")
            self.assertEqual(run["pages"][1]["state"], "failed")
            self.assertIn("page two exploded", run["pages"][1]["error"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_unknown_or_malformed_run_returns_404(self):
        self.assertEqual(self.client.get("/api/runs/" + "a" * 32).status_code, 404)
        self.assertEqual(self.client.get("/api/runs/not-a-run-id").status_code, 404)

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_compile_is_reused_when_tex_unchanged(self, compile_mock, generate_mock):
        generate_mock.return_value = {
            "title": "测试笔记",
            "blocks": [{"type": "paragraph", "text": "甲"}],
            "tex": "page one",
            "model": "test-model",
            "latency_ms": 1,
            "human_review": "required",
            "source_image": "p1.png",
        }
        compile_mock.side_effect = self._fake_compile
        response = self.client.post("/api/documents", files={"image": ("note.png", png(), "image/png")})
        data = response.json()
        directory = Path("artifacts/jobs") / data["job_id"]
        try:
            calls_after_upload = compile_mock.call_count
            first = self.client.post(f"/api/jobs/{data['job_id']}/compile", json={"tex": data["tex"]})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertTrue(first.json()["reused"])
            self.assertEqual(compile_mock.call_count, calls_after_upload)

            second = self.client.post(f"/api/jobs/{data['job_id']}/compile", json={"tex": "改过的内容"})
            self.assertEqual(second.status_code, 200, second.text)
            self.assertNotIn("reused", second.json())
            self.assertEqual(compile_mock.call_count, calls_after_upload + 1)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_history_can_be_listed_and_restored(self, compile_mock, generate_mock):
        generate_mock.return_value = {
            "title": "测试笔记",
            "blocks": [{"type": "paragraph", "text": "甲"}],
            "tex": "page one",
            "model": "test-model",
            "latency_ms": 1,
            "human_review": "required",
            "source_image": "p1.png",
        }
        compile_mock.side_effect = self._fake_compile
        response = self.client.post("/api/documents", files={"image": ("note.png", png(), "image/png")})
        data = response.json()
        job_id = data["job_id"]
        directory = Path("artifacts/jobs") / job_id
        try:
            edited = "我手动改过的版本"
            self.assertEqual(
                self.client.post(f"/api/jobs/{job_id}/compile", json={"tex": edited}).status_code, 200
            )

            listing = self.client.get(f"/api/jobs/{job_id}/history")
            self.assertEqual(listing.status_code, 200, listing.text)
            history = listing.json()["history"]
            self.assertGreaterEqual(len(history), 2)
            current = next(entry for entry in history if entry["is_current"])
            older = next(entry for entry in history if not entry["is_current"])
            self.assertEqual(current["first_line"], edited)

            restored = self.client.post(f"/api/jobs/{job_id}/restore-history", json={"name": older["name"]})
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json()["tex"], data["tex"])
            self.assertEqual((directory / "main.tex").read_text(encoding="utf-8"), data["tex"])

            self.assertEqual(
                self.client.post(f"/api/jobs/{job_id}/restore-history", json={"name": "../main.tex"}).status_code,
                400,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/jobs/{job_id}/restore-history", json={"name": "f" * 32 + ".tex"}
                ).status_code,
                404,
            )
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_status_reports_real_environment_facts_without_leaking_secrets(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["version"], VERSION)
        self.assertIn(data["build"]["source"], {"开发仓库", "安装包"})
        self.assertIsInstance(data["page_concurrency"], int)
        self.assertTrue(data["jobs"]["directory"].endswith(os.path.join("artifacts", "jobs")))
        self.assertIn("checks", data)
        self.assertTrue({check["level"] for check in data["checks"]} <= {"ok", "warn", "bad"})
        self.assertIn("used_by", data["recognizer"])
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            self.assertNotIn(api_key, response.text)
        self.assertEqual(data["openai"]["configured"], bool(api_key.strip()))

    def test_tectonic_version_reports_whole_first_line(self):
        completed = SimpleNamespace(stdout="Tectonic 0.15.0\n", stderr="")
        with patch("workbench.app._cached_status", side_effect=lambda key, producer: producer()), patch(
            "workbench.app._find_tectonic", return_value=Path("tools/tectonic/tectonic.exe")
        ), patch("workbench.app.subprocess.run", return_value=completed):
            status = _tectonic_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["version"], "Tectonic 0.15.0")

    def test_build_info_reads_bom_prefixed_json(self):
        payload = json.dumps(
            {"version": "1.0.0", "commit": "abc1234", "built_at": "2026-11-23 10:00:00 +08:00", "source": "安装包"},
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_info = root / "BUILD_INFO.json"
            build_info.write_text(payload, encoding="utf-8-sig")
            # 安装包/绿色包里没有 .git，所以 _PROJECT_ROOT 也要指到没有 .git 的临时目录，
            # 否则会被判成开发仓库（见 test_build_info_ignores_stale_file_in_dev_checkout）。
            with patch("workbench.app._PROJECT_ROOT", root), patch("workbench.app._BUILD_INFO_PATH", build_info):
                info = _build_info()
        self.assertEqual(info["source"], "安装包")
        self.assertEqual(info["commit"], "abc1234")
        self.assertEqual(info["built_at"], "2026-11-23 10:00:00 +08:00")

    def test_build_info_ignores_stale_file_in_dev_checkout(self):
        """开发仓库（有 .git）里即使躺着 BUILD_INFO.json，也不许报成"安装包"。

        这个文件曾经被提交进仓库，于是开发仓库里永远有一份上一次打包的
        commit/built_at。/api/status 照着它报，就把排查引到一个早已不存在的提交上。
        """
        payload = json.dumps(
            {"version": "1.0.0", "commit": "b9fae78", "built_at": "2026-11-25 07:47:38 +08:00", "source": "安装包"},
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            build_info = root / "BUILD_INFO.json"
            build_info.write_text(payload, encoding="utf-8-sig")
            with patch("workbench.app._PROJECT_ROOT", root), patch("workbench.app._BUILD_INFO_PATH", build_info):
                info = _build_info()
        self.assertEqual(info["source"], "开发仓库")
        self.assertNotEqual(info["commit"], "b9fae78")
        self.assertIsNone(info["built_at"])

    def test_python_runtime_tells_bundled_from_local(self):
        bundled = str(_PROJECT_ROOT / "runtime" / "python" / "python.exe")
        with patch("workbench.app.sys.executable", bundled):
            runtime = _python_runtime()
        self.assertTrue(runtime["bundled"])
        self.assertIn("安装包", runtime["source"])
        self.assertEqual(runtime["executable"], str(Path(bundled).resolve()))

        local = str(_PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")
        with patch("workbench.app.sys.executable", local):
            runtime = _python_runtime()
        self.assertFalse(runtime["bundled"])
        self.assertIn("本机", runtime["source"])

    # ---- 以下三个测试针对 2026-11-25 修掉的后端缺陷 ----

    def test_text_file_renamed_png_is_rejected_before_recognition(self):
        """文本改名 .png 应该在读入时就 400，而不是走到识别再报 502。

        这是"提示不达意"那条缺陷的回归测试：以前会一路走到识别阶段，
        最后抛出"整页识别或编译失败，请检查服务配置"，把人引去查密钥和编译器。
        """
        with patch("workbench.app.generate_document") as generate_mock:
            response = self.client.post(
                "/api/documents",
                files={"image": ("fake.png", b"this is plain text, not an image", "image/png")},
            )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("不是有效的图片文件", response.text)
        # 关键：根本没进识别，不浪费配额
        generate_mock.assert_not_called()

    def test_empty_file_is_rejected_with_clear_message(self):
        with patch("workbench.app.generate_document") as generate_mock:
            response = self.client.post(
                "/api/documents",
                files={"image": ("empty.png", b"", "image/png")},
            )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("空", response.text)
        generate_mock.assert_not_called()

    def test_jpeg_content_saved_with_true_suffix(self):
        """扩展名写 .png 但内容其实是 JPEG 时，落盘用真实格式的后缀。

        否则源图存成 source.png 却是 JPEG 内容，后面 \\includegraphics 或
        其他按后缀判断类型的代码会出错。
        """
        jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 32
        with patch("workbench.app.generate_document") as generate_mock, \
             patch("workbench.app.compile_tex") as compile_mock:
            generate_mock.return_value = {
                "title": "t",
                "blocks": [{"type": "paragraph", "text": "x"}],
                "tex": "\\documentclass{ctexart}\\begin{document}x\\end{document}",
                "latency_ms": 1.0,
                "human_review": "required",
                "signals": {},
            }
            compile_mock.return_value = {"success": True, "log": "", "errors": [], "returncode": 0}
            response = self.client.post(
                "/api/documents",
                files={"image": ("photo.png", jpeg, "image/png")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        directory = Path("artifacts/jobs") / response.json()["job_id"]
        try:
            stored = list((directory / "page_01").glob("source.*"))
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].suffix, ".jpg", "应按真实格式落盘，而不是扩展名")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_concurrent_compile_does_not_lose_writes(self):
        """同一任务并发编译时，最终磁盘内容必须是某一个请求的完整结果。

        以前没有按 job 加锁：两个请求都返回 200 成功，但后写的顶掉先写的，
        先到的那个拿到的是假成功。
        """
        from workbench.app import _compile_locked, _job_write_lock

        job_id = uuid.uuid4().hex
        directory = Path("artifacts/jobs") / job_id
        directory.mkdir(parents=True)
        base = "\\documentclass{ctexart}\\begin{document}x\\end{document}"
        (directory / "main.tex").write_text(base, encoding="utf-8")

        results: list[str] = []

        def worker(tag: str) -> None:
            tex = base + f"\n%{tag}"
            # 读也要在锁内：另一个线程的 _write_main_tex 用的是 write_text，
            # 它是"先截断再写"——锁外读会撞上截断后、写回前的空文件，
            # 于是这个测试会自己抖出一个和产品代码无关的假失败。
            with _job_write_lock(job_id):
                _compile_locked(job_id, directory, tex)
                results.append((directory / "main.tex").read_text(encoding="utf-8"))

        try:
            with patch("workbench.app.compile_tex") as compile_mock:
                compile_mock.return_value = {"success": True, "log": "", "errors": [], "returncode": 0}
                threads = [threading.Thread(target=worker, args=(t,)) for t in ("A", "B")]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
        finally:
            shutil.rmtree(directory, ignore_errors=True)

        # 两个线程各自读到的内容，都必须是"自己写完之后"的完整版本之一，
        # 而且都得以 \end{document} 收尾（不能被另一个线程截断成半截文件）。
        self.assertEqual(len(results), 2)
        for text in results:
            self.assertIn("\\end{document}", text)
            self.assertTrue(text.endswith("%A") or text.endswith("%B"), text[-20:])


if __name__ == "__main__":
    unittest.main()
