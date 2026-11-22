import json
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
            files={"image": ("note.png", b"image-bytes", "image/png")},
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
                (page_directory / "source.png").write_bytes(b"image")
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
        self.assertEqual([page["merged_page"] for page in data["pages"]], [1, None, 2])
        # 源图三个目录都在（失败页的原图也保留），失败页没有 original.tex
        self.assertTrue((Path("artifacts/jobs") / job_id / "page_01" / "original.tex").is_file())
        self.assertFalse((Path("artifacts/jobs") / job_id / "page_02" / "original.tex").exists())
        self.assertTrue((Path("artifacts/jobs") / job_id / "page_03" / "original.tex").is_file())
        page_two_source = self.client.get(f"/api/jobs/{job_id}/pages/2/source")
        self.assertEqual(page_two_source.content, b"second")
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
                ("image", ("p1.png", b"first", "image/png")),
                ("image", ("p2.png", b"second", "image/png")),
                ("image", ("p3.png", b"third", "image/png")),
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

    def test_job_list_supports_search_and_pagination(self):
        directories = []
        try:
            for index, title in enumerate(("分页验收A", "分页验收B", "其他任务")):
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

            first = self.client.get("/api/jobs", params={"q": "分页验收", "limit": 1, "offset": 0})
            second = self.client.get("/api/jobs", params={"q": "分页验收", "limit": 1, "offset": 1})
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

    @patch("workbench.app.compile_tex")
    def test_use_source_figures_rebuilds_without_recognition(self, compile_mock):
        directory = Path("artifacts/jobs") / uuid.uuid4().hex
        page_directory = directory / "page_01"
        page_directory.mkdir(parents=True)
        try:
            (page_directory / "source.png").write_bytes(b"image")
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


if __name__ == "__main__":
    unittest.main()
