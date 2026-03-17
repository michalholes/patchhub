# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_derived import (
    load_derived_payload,
    read_effective_event_tail_text,
    read_effective_log_tail,
)


def _write_cfg(repo_root: Path) -> None:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "\n".join(
            [
                "[web_jobs_retention]",
                "max_completed_job_raw_log_lines = 2",
                "max_completed_job_raw_event_lines = 1",
                "max_completed_job_raw_age_days = 3650",
                "keep_recent_terminal_jobs_per_mode = 1",
                "compact_tail_lines = 2",
                'reclaim_trigger_policy = "manual"',
                "reclaim_interval_seconds = 0",
                "reclaim_min_pruned_rows = 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _build_db(tmp_path: Path) -> WebJobsDatabase:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    _write_cfg(repo_root)
    return WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))


def _create_terminal_job(db: WebJobsDatabase, *, job_id: str, created_utc: str) -> None:
    job = JobRecord(
        job_id=job_id,
        created_utc=created_utc,
        mode="patch",
        issue_id="516",
        commit_summary=job_id,
        patch_basename="issue_516.zip",
        raw_command="python3 scripts/am_patch.py 516",
        canonical_command=["python3", "scripts/am_patch.py", "516"],
        status="running",
    )
    db.upsert_job(job)
    db.append_log_line(job_id, "l1")
    db.append_log_line(job_id, "l2")
    db.append_log_line(job_id, "l3")
    db.append_event_line(job_id, '{"type":"log","msg":"e1"}')
    db.append_event_line(job_id, '{"type":"status","event":"done"}')
    job.status = "success"
    job.ended_utc = created_utc
    db.upsert_job(job)


def test_retention_compacts_old_terminal_jobs_but_keeps_recent_mode_exemption(
    tmp_path: Path,
) -> None:
    db = _build_db(tmp_path)
    _create_terminal_job(
        db,
        job_id="job-516-old",
        created_utc="2026-03-08T10:00:00Z",
    )
    _create_terminal_job(
        db,
        job_id="job-516-new",
        created_utc="2026-03-09T10:00:00Z",
    )

    with db._store._connect() as conn:  # noqa: SLF001
        old_logs = conn.execute(
            "SELECT COUNT(*) AS n FROM web_job_log_lines WHERE job_id = ?",
            ("job-516-old",),
        ).fetchone()["n"]
        new_logs = conn.execute(
            "SELECT COUNT(*) AS n FROM web_job_log_lines WHERE job_id = ?",
            ("job-516-new",),
        ).fetchone()["n"]
    assert old_logs == 0
    assert new_logs == 3

    old_derived = load_derived_payload(db, "job-516-old")
    new_derived = load_derived_payload(db, "job-516-new")
    assert old_derived is not None
    assert new_derived is not None
    assert old_derived["compact_log_tail_text"] == "l2\nl3"
    assert old_derived["compact_event_tail_text"] == (
        '{"type":"log","msg":"e1"}\n{"type":"status","event":"done"}'
    )
    assert read_effective_log_tail(db, "job-516-old", lines=2) == "l2\nl3"
    assert read_effective_log_tail(db, "job-516-new", lines=2) == "l2\nl3"
    assert read_effective_event_tail_text(db, "job-516-old", lines=2) == (
        '{"type":"log","msg":"e1"}\n{"type":"status","event":"done"}'
    )
    assert db.legacy_event_text("job-516-old") == (
        '{"type":"log","msg":"e1"}\n{"type":"status","event":"done"}'
    )
