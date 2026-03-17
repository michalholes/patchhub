# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_fs import api_fs_list, api_fs_mkdir, api_fs_read_text, api_fs_stat
from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_virtual_fs import WebJobsVirtualFs


@dataclass
class _DummyFsSelf:
    virtual_jobs_fs: WebJobsVirtualFs


def _build_db(tmp_path: Path) -> WebJobsDatabase:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    return WebJobsDatabase(cfg)


def _seed_job(db: WebJobsDatabase, job_id: str = "job-514") -> None:
    db.upsert_job(
        JobRecord(
            job_id=job_id,
            created_utc="2026-03-09T10:00:00Z",
            mode="patch",
            issue_id="514",
            commit_summary="DB primary",
            patch_basename="issue_514.zip",
            raw_command="python3 scripts/am_patch.py 514",
            canonical_command=["python3", "scripts/am_patch.py", "514"],
            status="success",
        )
    )
    db.append_log_line(job_id, "alpha")
    db.append_log_line(job_id, "beta")
    db.append_event_line(job_id, '{"type":"log","msg":"queued"}')


def test_virtual_fs_reads_db_backed_job_files(tmp_path: Path) -> None:
    db = _build_db(tmp_path)
    _seed_job(db)
    vfs = WebJobsVirtualFs(db=db, enabled=True)

    root_items = vfs.list_dir("artifacts")
    assert root_items == [{"name": "web_jobs", "is_dir": True}]

    job_items = vfs.list_dir("artifacts/web_jobs/job-514")
    assert {item["name"] for item in job_items} == {
        "job.json",
        "runner.log",
        "am_patch_issue_514.jsonl",
    }

    stat_payload = vfs.json_stat_payload("artifacts/web_jobs/job-514/runner.log")
    assert stat_payload["exists"] is True
    assert stat_payload["virtual"] is True

    payload = json.loads(vfs.read_text("artifacts/web_jobs/job-514/job.json") or "{}")
    assert payload["job_id"] == "job-514"
    assert (
        vfs.read_text(
            "artifacts/web_jobs/job-514/runner.log",
            tail_lines=1,
        )
        == "beta"
    )

    download = vfs.download("artifacts/web_jobs/job-514/am_patch_issue_514.jsonl")
    assert download is not None
    assert download.filename == "am_patch_issue_514.jsonl"
    assert download.data.decode("utf-8") == '{"type":"log","msg":"queued"}'


def test_virtual_fs_api_surface_is_read_only(tmp_path: Path) -> None:
    db = _build_db(tmp_path)
    _seed_job(db)
    self_obj = _DummyFsSelf(virtual_jobs_fs=WebJobsVirtualFs(db=db, enabled=True))

    status, raw = api_fs_list(self_obj, "artifacts/web_jobs")
    assert status == 200
    assert json.loads(raw.decode("utf-8"))["virtual"] is True

    status, raw = api_fs_stat(self_obj, "artifacts/web_jobs/job-514/runner.log")
    assert status == 200
    assert json.loads(raw.decode("utf-8"))["virtual"] is True

    status, raw = api_fs_read_text(
        self_obj,
        {"path": "artifacts/web_jobs/job-514/runner.log", "tail_lines": "1"},
    )
    payload = json.loads(raw.decode("utf-8"))
    assert status == 200
    assert payload["text"] == "beta"
    assert payload["virtual"] is True

    status, raw = api_fs_mkdir(self_obj, {"path": "artifacts/web_jobs/job-514/new"})
    payload = json.loads(raw.decode("utf-8"))
    assert status == 409
    assert payload["error"] == "Virtual DB-backed path is read-only"
