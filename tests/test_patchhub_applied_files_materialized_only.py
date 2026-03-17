# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.models import JobRecord
from patchhub.run_applied_files import collect_job_applied_files
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_migration import _migrate


class _DbNoReparse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.read_full_log_calls = 0

    def load_job_json(self, job_id: str) -> dict[str, object] | None:
        del job_id
        return dict(self._payload)

    def read_full_log(self, job_id: str) -> str:
        del job_id
        self.read_full_log_calls += 1
        raise AssertionError("collect_job_applied_files must not reparse DB log")


def _build_db(tmp_path: Path) -> WebJobsDatabase:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    return WebJobsDatabase(cfg)


def test_db_primary_lookup_uses_only_materialized_applied_files() -> None:
    job = type("Job", (), {"status": "success", "job_id": "job-514"})()
    payload = {
        "job_id": "job-514",
        "applied_files": ["scripts/patchhub/app_api_fs.py"],
        "applied_files_source": "final_summary",
    }
    db = _DbNoReparse(payload)

    files, source = collect_job_applied_files(
        patches_root=Path("."),
        jobs_root=Path("."),
        job=job,
        job_db=db,  # type: ignore[arg-type]
    )

    assert files == ["scripts/patchhub/app_api_fs.py"]
    assert source == "final_summary"
    assert db.read_full_log_calls == 0

    unavailable = _DbNoReparse(
        {
            "job_id": "job-514",
            "applied_files": [],
            "applied_files_source": "unavailable",
        }
    )
    files, source = collect_job_applied_files(
        patches_root=Path("."),
        jobs_root=Path("."),
        job=job,
        job_db=unavailable,  # type: ignore[arg-type]
    )
    assert files == []
    assert source == "unavailable"
    assert unavailable.read_full_log_calls == 0


def test_success_upsert_materializes_applied_files_before_success_save(
    tmp_path: Path,
) -> None:
    db = _build_db(tmp_path)
    job = JobRecord(
        job_id="job-514-success",
        created_utc="2026-03-09T10:00:00Z",
        mode="patch",
        issue_id="514",
        commit_summary="DB primary",
        patch_basename="issue_514.zip",
        raw_command="python3 scripts/am_patch.py 514",
        canonical_command=["python3", "scripts/am_patch.py", "514"],
        status="running",
    )
    db.upsert_job(job)
    db.append_log_line("job-514-success", "FILES:")
    db.append_log_line("job-514-success", "scripts/patchhub/app_api_fs.py")

    job.status = "success"
    job.ended_utc = "2026-03-09T10:05:00Z"
    db.upsert_job(job)

    payload = db.load_job_json("job-514-success")
    assert payload is not None
    assert payload["status"] == "success"
    assert payload["applied_files"] == ["scripts/patchhub/app_api_fs.py"]
    assert payload["applied_files_source"] == "final_summary"


def test_migration_backfills_materialized_applied_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    job_dir = repo_root / "patches" / "artifacts" / "web_jobs" / "job-514-migrate"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-514-migrate",
                "created_utc": "2026-03-09T10:00:00Z",
                "mode": "patch",
                "issue_id": "514",
                "commit_summary": "DB primary",
                "patch_basename": "issue_514.zip",
                "raw_command": "python3 scripts/am_patch.py 514",
                "canonical_command": ["python3", "scripts/am_patch.py", "514"],
                "status": "success",
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (job_dir / "runner.log").write_text(
        "FILES:\nscripts/patchhub/app_api_fs.py\n",
        encoding="utf-8",
    )
    (job_dir / "am_patch_issue_514.jsonl").write_text(
        '{"type":"status","event":"done"}\n',
        encoding="utf-8",
    )

    imported = _migrate(repo_root)
    assert imported == ["job-514-migrate"]

    db = WebJobsDatabase(load_web_jobs_db_config(repo_root, repo_root / "patches"))
    payload = db.load_job_json("job-514-migrate")
    assert payload is not None
    assert payload["applied_files"] == ["scripts/patchhub/app_api_fs.py"]
    assert payload["applied_files_source"] == "final_summary"
