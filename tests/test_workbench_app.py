import os
import shutil
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from workbench.app import app


class WorkbenchAppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

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
            files={"image": ("note.png", b"image-bytes", "image/png")},
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
                ("image", ("p1.png", b"first", "image/png")),
                ("image", ("p2.png", b"second", "image/png")),
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
        self.assertEqual(page_two_source.content, b"second")

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
                ("image", ("p1.png", b"first", "image/png")),
                ("image", ("p2.png", b"second", "image/png")),
                ("image", ("p3.png", b"third", "image/png")),
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
        # 源图三个目录都在（失败页的原图也保留），失败页没有 original.tex
        self.assertTrue((Path("artifacts/jobs") / job_id / "page_01" / "original.tex").is_file())
        self.assertFalse((Path("artifacts/jobs") / job_id / "page_02" / "original.tex").exists())
        self.assertTrue((Path("artifacts/jobs") / job_id / "page_03" / "original.tex").is_file())
        page_two_source = self.client.get(f"/api/jobs/{job_id}/pages/2/source")
        self.assertEqual(page_two_source.content, b"second")
        self.assertTrue(data["compile"]["success"])

    @patch("workbench.app.generate_document")
    @patch("workbench.app.compile_tex")
    def test_batch_upload_all_pages_fail_returns_502(self, compile_mock, generate_mock):
        generate_mock.side_effect = [RuntimeError("first down"), RuntimeError("second down")]

        response = self.client.post(
            "/api/documents/batch",
            files=[
                ("image", ("p1.png", b"first", "image/png")),
                ("image", ("p2.png", b"second", "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 502)
        compile_mock.assert_not_called()

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

    def test_missing_job_returns_404(self):
        response = self.client.get("/api/jobs/00000000000000000000000000000000/pdf")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
