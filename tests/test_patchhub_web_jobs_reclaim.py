# ruff: noqa: E402
from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_derived import (
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
                "max_completed_job_raw_log_lines = 1",
                "max_completed_job_raw_event_lines = 1",
                "max_completed_job_raw_age_days = 3650",
                "keep_recent_terminal_jobs_per_mode = 0",
                "compact_tail_lines = 1",
                'reclaim_trigger_policy = "after_compaction"',
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


def test_compaction_updates_housekeeping_and_keeps_reads_usable(tmp_path: Path) -> None:
    db = _build_db(tmp_path)
    db_path = db.cfg.db_path
    job = JobRecord(
        job_id="job-516-reclaim",
        created_utc="2026-03-09T10:00:00Z",
        mode="patch",
        issue_id="516",
        commit_summary="reclaim",
        patch_basename="issue_516.zip",
        raw_command="python3 scripts/am_patch.py 516",
        canonical_command=["python3", "scripts/am_patch.py", "516"],
        status="running",
    )
    db.upsert_job(job)
    db.append_log_line(job.job_id, "alpha")
    db.append_log_line(job.job_id, "beta")
    db.append_event_line(job.job_id, '{"type":"status","event":"done"}')
    db.append_event_line(job.job_id, '{"type":"summary","msg":"beta"}')

    size_before = os.path.getsize(db_path)
    job.status = "success"
    job.ended_utc = "2026-03-09T10:05:00Z"
    db.upsert_job(job)
    size_after = os.path.getsize(db_path)

    with db._store._connect() as conn:  # noqa: SLF001
        hk = conn.execute(
            "SELECT last_reclaim_unix_ms, prune_ops, "
            "pruned_log_rows, pruned_event_rows "
            "FROM web_jobs_housekeeping WHERE singleton = 1"
        ).fetchone()
        remaining_logs = conn.execute(
            "SELECT COUNT(*) AS n FROM web_job_log_lines WHERE job_id = ?",
            (job.job_id,),
        ).fetchone()["n"]
    assert hk is not None
    assert int(hk["last_reclaim_unix_ms"]) > 0
    assert int(hk["prune_ops"]) >= 1
    assert int(hk["pruned_log_rows"]) == 2
    assert int(hk["pruned_event_rows"]) == 2
    assert remaining_logs == 0
    assert read_effective_log_tail(db, job.job_id, lines=1) == "beta"
    assert db.read_full_log(job.job_id) == "beta"
    assert read_effective_event_tail_text(db, job.job_id, lines=1) == (
        '{"type":"summary","msg":"beta"}'
    )
    assert db.legacy_event_text(job.job_id) == ('{"type":"summary","msg":"beta"}')
    assert size_after <= size_before + 8192
