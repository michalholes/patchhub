# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config


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


def test_export_legacy_tree_uses_compact_compatibility_text_after_compaction(
    tmp_path: Path,
) -> None:
    db = _build_db(tmp_path)
    job = JobRecord(
        job_id="job-516-export",
        created_utc="2026-03-09T11:00:00Z",
        mode="patch",
        issue_id="516",
        commit_summary="legacy export",
        patch_basename="issue_516.zip",
        raw_command="python3 scripts/am_patch.py 516",
        canonical_command=["python3", "scripts/am_patch.py", "516"],
        status="running",
    )
    db.upsert_job(job)
    db.append_log_line(job.job_id, "alpha")
    db.append_log_line(job.job_id, "beta")
    db.append_event_line(job.job_id, '{"type":"log","msg":"alpha"}')
    db.append_event_line(job.job_id, '{"type":"summary","msg":"beta"}')
    job.status = "success"
    job.ended_utc = "2026-03-09T11:05:00Z"
    db.upsert_job(job)

    export_root = tmp_path / "legacy_export"
    db.export_legacy_tree(export_root)

    assert (export_root / job.job_id / "runner.log").read_text(encoding="utf-8") == "alpha\nbeta"
    assert (export_root / job.job_id / "am_patch_issue_516.jsonl").read_text(
        encoding="utf-8"
    ) == '{"type":"log","msg":"alpha"}\n{"type":"summary","msg":"beta"}'
