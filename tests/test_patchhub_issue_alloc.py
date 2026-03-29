# ruff: noqa: E402
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.issue_alloc import allocate_next_issue_id


class TestIssueAlloc(unittest.TestCase):
    def test_allocate_start(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "logs").mkdir(parents=True)
            n = allocate_next_issue_id(root, r"issue_(\d+)", 1, 99999)
            self.assertEqual(n, 1)

    def test_allocate_next(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "logs").mkdir(parents=True)
            (root / "logs" / "am_patch_issue_41_x.log").write_text("hi", encoding="utf-8")
            n = allocate_next_issue_id(root, r"issue_(\d+)", 1, 99999)
            self.assertEqual(n, 42)

    def test_allocate_next_uses_web_jobs_db_max_issue_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifacts = root / "artifacts"
            artifacts.mkdir(parents=True)
            conn = sqlite3.connect(str(artifacts / "web_jobs.sqlite3"))
            try:
                conn.execute("CREATE TABLE web_jobs (issue_id_int INTEGER)")
                conn.execute("INSERT INTO web_jobs(issue_id_int) VALUES (52)")
                conn.commit()
            finally:
                conn.close()
            n = allocate_next_issue_id(root, r"issue_(\d+)", 1, 99999)
            self.assertEqual(n, 53)

    def test_allocate_next_uses_legacy_job_records_when_filesystem_markers_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job_dir = root / "artifacts" / "web_jobs" / "job-001"
            job_dir.mkdir(parents=True)
            (job_dir / "job.json").write_text(
                '{"job_id":"job-001","issue_id":"61","status":"success","mode":"patch"}',
                encoding="utf-8",
            )
            n = allocate_next_issue_id(root, r"issue_(\d+)", 1, 99999)
            self.assertEqual(n, 62)
