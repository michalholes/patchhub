# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_virtual_fs import WebJobsVirtualFs


def _write_cfg(repo_root: Path) -> None:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "\n".join(
            [
                "[web_jobs_retention]",
                "max_completed_job_raw_log_lines = 1",
                "max_completed_job_raw_event_lines = 1",
                "max_completed_job_raw_age_days = 3650",
                "keep_recent_terminal_jobs_per_mode = 0",
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


def _seed_compacted_job(db: WebJobsDatabase) -> str:
    job_id = "job-516-virtual"
    job = JobRecord(
        job_id=job_id,
        created_utc="2026-03-09T10:00:00Z",
        mode="patch",
        issue_id="516",
        commit_summary="virtual compatibility",
        patch_basename="issue_516.zip",
        raw_command="python3 scripts/am_patch.py 516",
        canonical_command=["python3", "scripts/am_patch.py", "516"],
        status="running",
    )
    db.upsert_job(job)
    db.append_log_line(job_id, "alpha")
    db.append_log_line(job_id, "beta")
    db.append_log_line(job_id, "gamma")
    db.append_event_line(job_id, '{"type":"log","msg":"alpha"}')
    db.append_event_line(job_id, '{"type":"summary","msg":"gamma"}')
    job.status = "success"
    job.ended_utc = "2026-03-09T10:05:00Z"
    db.upsert_job(job)
    return job_id


def test_virtual_fs_reads_compact_compatibility_text_after_raw_rows_are_pruned(
    tmp_path: Path,
) -> None:
    db = _build_db(tmp_path)
    job_id = _seed_compacted_job(db)
    vfs = WebJobsVirtualFs(db=db, enabled=True)

    with db._store._connect() as conn:  # noqa: SLF001
        raw_logs = conn.execute(
            "SELECT COUNT(*) AS n FROM web_job_log_lines WHERE job_id = ?",
            (job_id,),
        ).fetchone()["n"]
        raw_events = conn.execute(
            "SELECT COUNT(*) AS n FROM web_job_event_lines WHERE job_id = ?",
            (job_id,),
        ).fetchone()["n"]
    assert raw_logs == 0
    assert raw_events == 0

    assert vfs.read_text(f"artifacts/web_jobs/{job_id}/runner.log") == "beta\ngamma"
    assert vfs.read_text(f"artifacts/web_jobs/{job_id}/runner.log", tail_lines=1) == "gamma"
    assert vfs.read_text(f"artifacts/web_jobs/{job_id}/am_patch_issue_516.jsonl") == (
        '{"type":"log","msg":"alpha"}\n{"type":"summary","msg":"gamma"}'
    )
    assert (
        vfs.read_text(
            f"artifacts/web_jobs/{job_id}/am_patch_issue_516.jsonl",
            tail_lines=1,
        )
        == '{"type":"summary","msg":"gamma"}'
    )
