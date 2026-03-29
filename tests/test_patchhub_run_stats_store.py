# ruff: noqa: E402
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.asgi_app import create_app
from patchhub.config import load_config
from patchhub.run_stats_store import RunStatsStore
from patchhub.web_jobs_backup import _REQUIRED_TABLES as BACKUP_REQUIRED_TABLES
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_recovery import _REQUIRED_TABLES as RECOVERY_REQUIRED_TABLES


def _write_log(path: Path, text: str, *, mtime_s: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime_s, mtime_s))


def test_run_stats_store_incremental_ingest_uses_cursor_without_rereading_history(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    logs_root = patches_root / "logs"
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    store = RunStatsStore(cfg, patches_root)
    first = logs_root / "am_patch_issue_701_20260329_010101.log"
    second = logs_root / "am_patch_issue_702_20260329_020202.log"
    _write_log(first, "RESULT: SUCCESS\n", mtime_s=100)

    calls: list[str] = []

    def _fake_parse(log_path: Path, *, log_mtime_ns: int | None = None) -> tuple[str, str | None]:
        calls.append(log_path.name)
        return "success", "RESULT: SUCCESS"

    with patch("patchhub.run_stats_store.read_run_result_from_log", side_effect=_fake_parse):
        store.ingest_logs(r"am_patch_issue_(\d+)_")
        assert calls == [first.name]

        calls.clear()
        _write_log(second, "RESULT: FAIL\n", mtime_s=200)
        store.ingest_logs(r"am_patch_issue_(\d+)_")
        assert calls == [second.name]


def test_run_stats_store_preserves_history_and_exact_rolling_windows(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    logs_root = patches_root / "logs"
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    store = RunStatsStore(cfg, patches_root)
    now_ms = 20 * 86400 * 1000
    inside = int((now_ms - (6 * 86400 * 1000)) / 1000)
    outside = int((now_ms - (8 * 86400 * 1000)) / 1000)
    first = logs_root / "am_patch_issue_711_20260329_010101.log"
    second = logs_root / "am_patch_issue_712_20260329_020202.log"
    _write_log(first, "RESULT: SUCCESS\n", mtime_s=inside)
    _write_log(second, "RESULT: FAIL\n", mtime_s=outside)

    store.ingest_logs(r"am_patch_issue_(\d+)_")
    initial = store.build_summary([7], now_unix_ms=now_ms)
    assert initial.count == 2
    assert initial.stats.all_time.total == 2
    assert initial.stats.windows[0].days == 7
    assert initial.stats.windows[0].total == 1
    assert initial.stats.windows[0].success == 1
    assert initial.stats.windows[0].fail == 0

    second.unlink()
    store.ingest_logs(r"am_patch_issue_(\d+)_")
    after_cleanup = store.build_summary([7], now_unix_ms=now_ms)
    assert after_cleanup.count == 2
    assert after_cleanup.stats.all_time.fail == 1
    assert after_cleanup.stats.windows[0].total == 1


def test_ui_snapshot_header_uses_persisted_stats_while_runs_stay_logs_based(
    tmp_path: Path,
) -> None:
    cfg = load_config(
        Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    )
    log_path = tmp_path / "patches" / "logs" / "am_patch_issue_721_20260329_030303.log"
    _write_log(log_path, "RESULT: SUCCESS\n", mtime_s=300)

    app = create_app(repo_root=tmp_path, cfg=cfg)
    with TestClient(app) as client:
        first_snapshot = client.get("/api/ui_snapshot").json()
        assert first_snapshot["snapshot"]["header"]["runs"]["count"] == 1
        assert first_snapshot["snapshot"]["runs"][0]["issue_id"] == 721

        log_path.unlink()
        rescan = client.post("/api/debug/indexer/force_rescan")
        assert rescan.status_code == 200

        deadline = time.monotonic() + 2.0
        header_count = -1
        while time.monotonic() < deadline:
            snapshot = client.get("/api/ui_snapshot").json()
            header_count = int(snapshot["snapshot"]["header"]["runs"]["count"])
            runs_len = len(snapshot["snapshot"]["runs"])
            if header_count == 1 and runs_len == 0:
                break
            time.sleep(0.05)
        assert header_count == 1
        runs_resp = client.get("/api/runs").json()
        assert runs_resp["runs"] == []


def test_run_stats_tables_are_required_for_backup_and_recovery(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    assert "run_stats_meta" in BACKUP_REQUIRED_TABLES
    assert "run_stats_seen" in BACKUP_REQUIRED_TABLES
    assert "run_stats_meta" in RECOVERY_REQUIRED_TABLES
    assert "run_stats_seen" in RECOVERY_REQUIRED_TABLES

    WebJobsDatabase(cfg)
    with sqlite3.connect(str(cfg.db_path)) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "run_stats_meta" in tables
    assert "run_stats_seen" in tables
