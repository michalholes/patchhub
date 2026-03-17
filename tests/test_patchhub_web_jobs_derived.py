# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.models import JobRecord
from patchhub.run_applied_files import collect_job_applied_files
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_derived import (
    load_derived_payload,
    read_effective_event_tail_text,
    read_effective_full_event_text,
    read_effective_full_log,
    read_effective_log_tail,
)


def _write_cfg(repo_root: Path, body: str) -> None:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(body, encoding="utf-8")


def _build_db(tmp_path: Path) -> WebJobsDatabase:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    _write_cfg(
        repo_root,
        "\n".join(
            [
                "[web_jobs_retention]",
                "max_completed_job_raw_log_lines = 100000",
                "max_completed_job_raw_event_lines = 100000",
                "max_completed_job_raw_age_days = 3650",
                "keep_recent_terminal_jobs_per_mode = 0",
                "compact_tail_lines = 2",
                'reclaim_trigger_policy = "manual"',
                "reclaim_interval_seconds = 0",
                "reclaim_min_pruned_rows = 1",
            ]
        )
        + "\n",
    )
    return WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))


def test_terminal_success_materializes_low_churn_derived_payload(
    tmp_path: Path,
) -> None:
    db = _build_db(tmp_path)
    job = JobRecord(
        job_id="job-516-derived",
        created_utc="2026-03-09T10:00:00Z",
        mode="patch",
        issue_id="516",
        commit_summary="derived payload",
        patch_basename="issue_516.zip",
        raw_command="python3 scripts/am_patch.py 516",
        canonical_command=["python3", "scripts/am_patch.py", "516"],
        status="running",
    )
    db.upsert_job(job)
    db.append_log_line("job-516-derived", "FILES:")
    db.append_log_line("job-516-derived", "scripts/patchhub/app_api_jobs.py")
    db.append_event_line("job-516-derived", '{"type":"status","event":"done"}')

    job.status = "success"
    job.ended_utc = "2026-03-09T10:05:00Z"
    db.upsert_job(job)

    derived = load_derived_payload(db, "job-516-derived")
    assert derived is not None
    assert derived["applied_files"] == ["scripts/patchhub/app_api_jobs.py"]
    assert derived["applied_files_source"] == "final_summary"
    assert (
        derived["compact_log_tail_text"] == "FILES:\nscripts/patchhub/app_api_jobs.py"
    )
    assert derived["compact_event_tail_text"] == '{"type":"status","event":"done"}'

    with db._store._connect() as conn:  # noqa: SLF001
        conn.execute(
            (
                "UPDATE web_jobs SET applied_files_json = '[]', "
                "applied_files_source = 'unavailable' WHERE job_id = ?"
            ),
            ("job-516-derived",),
        )

    files, source = collect_job_applied_files(
        patches_root=Path("."),
        jobs_root=Path("."),
        job=job,
        job_db=db,
    )
    assert files == ["scripts/patchhub/app_api_jobs.py"]
    assert source == "final_summary"
    assert (
        read_effective_log_tail(
            db,
            "job-516-derived",
            lines=1,
        )
        == "scripts/patchhub/app_api_jobs.py"
    )
    assert read_effective_full_log(db, "job-516-derived") == (
        "FILES:\nscripts/patchhub/app_api_jobs.py"
    )
    assert read_effective_full_event_text(db, "job-516-derived") == (
        '{"type":"status","event":"done"}'
    )


def test_compacted_event_tail_keeps_20000_lines_when_config_requests_it(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    _write_cfg(
        repo_root,
        "\n".join(
            [
                "[web_jobs_retention]",
                "max_completed_job_raw_log_lines = 1",
                "max_completed_job_raw_event_lines = 1",
                "max_completed_job_raw_age_days = 3650",
                "keep_recent_terminal_jobs_per_mode = 0",
                "compact_tail_lines = 20000",
                'reclaim_trigger_policy = "manual"',
                "reclaim_interval_seconds = 0",
                "reclaim_min_pruned_rows = 1",
            ]
        )
        + "\n",
    )
    db = WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))
    job = JobRecord(
        job_id="job-533-derived",
        created_utc="2026-03-09T10:00:00Z",
        mode="patch",
        issue_id="533",
        commit_summary="derived payload",
        patch_basename="issue_533.zip",
        raw_command="python3 scripts/am_patch.py 533",
        canonical_command=["python3", "scripts/am_patch.py", "533"],
        status="running",
    )
    db.upsert_job(job)
    for idx in range(20_005):
        db.append_event_line(
            job.job_id,
            f'{{"type":"log","msg":"{idx}"}}',
        )

    job.status = "success"
    job.ended_utc = "2026-03-09T10:05:00Z"
    db.upsert_job(job)

    text = read_effective_event_tail_text(db, job.job_id, lines=99_999)
    lines = text.splitlines()
    assert len(lines) == 20_000
    assert lines[0] == '{"type":"log","msg":"5"}'
    assert lines[-1] == '{"type":"log","msg":"20004"}'
