from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from .models import EventRow, JobRecord, WebJobsDbConfig

_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_jobs (
    job_id TEXT PRIMARY KEY,
    created_utc TEXT NOT NULL,
    created_unix_ms INTEGER NOT NULL,
    mode TEXT NOT NULL,
    issue_id_raw TEXT NOT NULL,
    issue_id_int INTEGER,
    commit_summary TEXT NOT NULL,
    commit_message TEXT,
    patch_basename TEXT,
    raw_command TEXT NOT NULL,
    canonical_command_json TEXT NOT NULL,
    status TEXT NOT NULL,
    started_utc TEXT,
    ended_utc TEXT,
    return_code INTEGER,
    error TEXT,
    cancel_requested_utc TEXT,
    cancel_ack_utc TEXT,
    cancel_source TEXT,
    original_patch_path TEXT,
    effective_patch_path TEXT,
    effective_patch_kind TEXT,
    selected_patch_entries_json TEXT NOT NULL,
    selected_repo_paths_json TEXT NOT NULL,
    zip_target_repo TEXT,
    selected_target_repo TEXT,
    effective_runner_target_repo TEXT,
    target_mismatch INTEGER NOT NULL DEFAULT 0,
    applied_files_json TEXT NOT NULL,
    applied_files_source TEXT NOT NULL,
    last_log_seq INTEGER NOT NULL DEFAULT 0,
    last_event_seq INTEGER NOT NULL DEFAULT 0,
    row_rev INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS web_job_log_lines (
    job_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    line TEXT NOT NULL,
    PRIMARY KEY (job_id, seq)
);
CREATE TABLE IF NOT EXISTS web_job_event_lines (
    job_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    raw_line TEXT NOT NULL,
    ipc_seq INTEGER,
    frame_type TEXT,
    frame_event TEXT,
    PRIMARY KEY (job_id, seq)
);
CREATE TABLE IF NOT EXISTS web_jobs_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    jobs_rev INTEGER NOT NULL,
    logs_rev INTEGER NOT NULL,
    events_rev INTEGER NOT NULL,
    updated_unix_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS web_job_derived (
    job_id TEXT PRIMARY KEY,
    applied_files_json TEXT NOT NULL,
    applied_files_source TEXT NOT NULL,
    compact_log_tail_text TEXT NOT NULL,
    compact_event_tail_text TEXT NOT NULL,
    derived_rev INTEGER NOT NULL DEFAULT 0,
    created_utc TEXT NOT NULL,
    created_unix_ms INTEGER NOT NULL,
    updated_utc TEXT NOT NULL,
    updated_unix_ms INTEGER NOT NULL,
    source_row_rev INTEGER NOT NULL DEFAULT 0,
    raw_log_lines_compacted INTEGER NOT NULL DEFAULT 0,
    raw_event_lines_compacted INTEGER NOT NULL DEFAULT 0,
    terminal_status TEXT NOT NULL DEFAULT '',
    terminal_utc TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS web_jobs_housekeeping (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_reclaim_unix_ms INTEGER NOT NULL DEFAULT 0,
    prune_ops INTEGER NOT NULL DEFAULT 0,
    pruned_log_rows INTEGER NOT NULL DEFAULT 0,
    pruned_event_rows INTEGER NOT NULL DEFAULT 0,
    updated_unix_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_web_jobs_created_desc
    ON web_jobs(created_unix_ms DESC, job_id DESC);
CREATE INDEX IF NOT EXISTS idx_web_jobs_status_created
    ON web_jobs(status, created_unix_ms DESC, job_id DESC);
CREATE INDEX IF NOT EXISTS idx_web_jobs_issue_status_created
    ON web_jobs(issue_id_int, status, created_unix_ms DESC, job_id DESC);
CREATE INDEX IF NOT EXISTS idx_web_job_log_lines_tail
    ON web_job_log_lines(job_id, seq DESC);
CREATE INDEX IF NOT EXISTS idx_web_job_event_lines_tail
    ON web_job_event_lines(job_id, seq DESC);
"""


def _utc_now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _utc_to_unix_ms(value: str | None) -> int:
    if not value:
        return 0
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return 0
    return int(dt.replace(tzinfo=UTC).timestamp() * 1000)


def _safe_issue_id_int(value: str) -> int | None:
    raw = str(value or "").strip()
    return int(raw) if raw.isdigit() else None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _none_if_blank(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _read_event_frame(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


_WEB_JOBS_ADDITIVE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("commit_message", "TEXT"),
    ("zip_target_repo", "TEXT"),
    ("selected_target_repo", "TEXT"),
    ("effective_runner_target_repo", "TEXT"),
    ("target_mismatch", "INTEGER NOT NULL DEFAULT 0"),
)


def _ensure_web_jobs_additive_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(web_jobs)").fetchall()
    existing = {str(row[1]) for row in rows}
    for name, ddl in _WEB_JOBS_ADDITIVE_COLUMNS:
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE web_jobs ADD COLUMN {name} {ddl}")
        existing.add(name)


def _event_row_from_sql(row: sqlite3.Row) -> EventRow:
    return EventRow(
        seq=int(row["seq"]),
        raw_line=str(row["raw_line"]),
        ipc_seq=_int_or_none(row["ipc_seq"]),
        frame_type=_none_if_blank(row["frame_type"]),
        frame_event=_none_if_blank(row["frame_event"]),
    )


class SqliteWebJobsStore:
    def __init__(self, cfg: WebJobsDbConfig) -> None:
        self.cfg = cfg
        self.cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.cfg.db_path),
            timeout=float(self.cfg.connect_timeout_s),
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(f"PRAGMA busy_timeout={int(self.cfg.busy_timeout_ms)}")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.executescript(_SCHEMA)
            _ensure_web_jobs_additive_columns(conn)
            auto_vacuum = int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])
            if auto_vacuum != 2:
                conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
                conn.execute("VACUUM")
            now_ms = _utc_now_ms()
            conn.execute(
                """
                INSERT INTO web_jobs_meta(
                    singleton, jobs_rev, logs_rev, events_rev, updated_unix_ms
                ) VALUES(1, 0, 0, 0, ?)
                ON CONFLICT(singleton) DO NOTHING
                """,
                (now_ms,),
            )
            conn.execute(
                """
                INSERT INTO web_jobs_housekeeping(
                    singleton, last_reclaim_unix_ms, prune_ops,
                    pruned_log_rows, pruned_event_rows, updated_unix_ms
                ) VALUES(1, 0, 0, 0, 0, ?)
                ON CONFLICT(singleton) DO NOTHING
                """,
                (now_ms,),
            )

    def _touch_meta(
        self,
        conn: sqlite3.Connection,
        *,
        jobs_delta: int = 0,
        logs_delta: int = 0,
        events_delta: int = 0,
    ) -> None:
        conn.execute(
            """
            UPDATE web_jobs_meta
               SET jobs_rev = jobs_rev + ?,
                   logs_rev = logs_rev + ?,
                   events_rev = events_rev + ?,
                   updated_unix_ms = ?
             WHERE singleton = 1
            """,
            (jobs_delta, logs_delta, events_delta, _utc_now_ms()),
        )

    def _row_to_job_json(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": str(row["job_id"]),
            "created_utc": str(row["created_utc"]),
            "created_unix_ms": int(row["created_unix_ms"]),
            "mode": str(row["mode"]),
            "issue_id": str(row["issue_id_raw"]),
            "commit_summary": str(row["commit_summary"]),
            "commit_message": row["commit_message"],
            "patch_basename": row["patch_basename"],
            "raw_command": str(row["raw_command"]),
            "canonical_command": json.loads(str(row["canonical_command_json"])),
            "status": str(row["status"]),
            "started_utc": row["started_utc"],
            "ended_utc": row["ended_utc"],
            "return_code": row["return_code"],
            "error": row["error"],
            "cancel_requested_utc": row["cancel_requested_utc"],
            "cancel_ack_utc": row["cancel_ack_utc"],
            "cancel_source": row["cancel_source"],
            "original_patch_path": row["original_patch_path"],
            "effective_patch_path": row["effective_patch_path"],
            "effective_patch_kind": row["effective_patch_kind"],
            "selected_patch_entries": json.loads(str(row["selected_patch_entries_json"])),
            "selected_repo_paths": json.loads(str(row["selected_repo_paths_json"])),
            "zip_target_repo": row["zip_target_repo"],
            "selected_target_repo": row["selected_target_repo"],
            "effective_runner_target_repo": row["effective_runner_target_repo"],
            "target_mismatch": bool(row["target_mismatch"]),
            "applied_files": json.loads(str(row["applied_files_json"])),
            "applied_files_source": str(row["applied_files_source"]),
            "last_log_seq": int(row["last_log_seq"]),
            "last_event_seq": int(row["last_event_seq"]),
            "row_rev": int(row["row_rev"]),
        }

    def _current_row_rev(self, conn: sqlite3.Connection, job_id: str) -> int:
        row = conn.execute(
            "SELECT row_rev FROM web_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return int(row["row_rev"]) if row is not None else 0

    def _job_values(
        self,
        job: JobRecord,
        *,
        log_count: int | None = None,
        event_count: int | None = None,
        row_rev: int,
    ) -> tuple[Any, ...]:
        payload = job.to_json()
        return (
            job.job_id,
            str(payload.get("created_utc", "")),
            int(payload.get("created_unix_ms", 0) or _utc_to_unix_ms(job.created_utc)),
            str(job.mode),
            str(job.issue_id),
            _safe_issue_id_int(job.issue_id),
            str(job.commit_summary),
            job.commit_message,
            job.patch_basename,
            str(job.raw_command),
            _json_dumps(list(job.canonical_command)),
            str(job.status),
            job.started_utc,
            job.ended_utc,
            job.return_code,
            job.error,
            job.cancel_requested_utc,
            job.cancel_ack_utc,
            job.cancel_source,
            job.original_patch_path,
            job.effective_patch_path,
            job.effective_patch_kind,
            _json_dumps(list(job.selected_patch_entries)),
            _json_dumps(list(job.selected_repo_paths)),
            job.zip_target_repo,
            job.selected_target_repo,
            job.effective_runner_target_repo,
            1 if job.target_mismatch else 0,
            _json_dumps(list(job.applied_files)),
            str(job.applied_files_source),
            int(log_count if log_count is not None else job.last_log_seq),
            int(event_count if event_count is not None else job.last_event_seq),
            row_rev,
        )

    def _upsert_job_row(
        self,
        conn: sqlite3.Connection,
        job: JobRecord,
        *,
        log_count: int | None = None,
        event_count: int | None = None,
        row_rev: int,
    ) -> None:
        conn.execute(
            """
            INSERT INTO web_jobs(
                job_id, created_utc, created_unix_ms, mode,
                issue_id_raw, issue_id_int, commit_summary, commit_message,
                patch_basename, raw_command, canonical_command_json, status,
                started_utc, ended_utc, return_code, error,
                cancel_requested_utc, cancel_ack_utc, cancel_source,
                original_patch_path, effective_patch_path, effective_patch_kind,
                selected_patch_entries_json, selected_repo_paths_json,
                zip_target_repo, selected_target_repo,
                effective_runner_target_repo, target_mismatch,
                applied_files_json, applied_files_source,
                last_log_seq, last_event_seq, row_rev
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(job_id) DO UPDATE SET
                created_utc = excluded.created_utc,
                created_unix_ms = excluded.created_unix_ms,
                mode = excluded.mode,
                issue_id_raw = excluded.issue_id_raw,
                issue_id_int = excluded.issue_id_int,
                commit_summary = excluded.commit_summary,
                commit_message = excluded.commit_message,
                patch_basename = excluded.patch_basename,
                raw_command = excluded.raw_command,
                canonical_command_json = excluded.canonical_command_json,
                status = excluded.status,
                started_utc = excluded.started_utc,
                ended_utc = excluded.ended_utc,
                return_code = excluded.return_code,
                error = excluded.error,
                cancel_requested_utc = excluded.cancel_requested_utc,
                cancel_ack_utc = excluded.cancel_ack_utc,
                cancel_source = excluded.cancel_source,
                original_patch_path = excluded.original_patch_path,
                effective_patch_path = excluded.effective_patch_path,
                effective_patch_kind = excluded.effective_patch_kind,
                selected_patch_entries_json = excluded.selected_patch_entries_json,
                selected_repo_paths_json = excluded.selected_repo_paths_json,
                zip_target_repo = excluded.zip_target_repo,
                selected_target_repo = excluded.selected_target_repo,
                effective_runner_target_repo = excluded.effective_runner_target_repo,
                target_mismatch = excluded.target_mismatch,
                applied_files_json = excluded.applied_files_json,
                applied_files_source = excluded.applied_files_source,
                last_log_seq = excluded.last_log_seq,
                last_event_seq = excluded.last_event_seq,
                row_rev = excluded.row_rev
            """,
            self._job_values(
                job,
                log_count=log_count,
                event_count=event_count,
                row_rev=row_rev,
            ),
        )
        if str(job.status) in {"success", "fail", "canceled"}:
            from .web_jobs_derived import ensure_job_derived_row
            from .web_jobs_retention import (
                load_retention_settings,
                maybe_compact_terminal_job,
            )

            settings = load_retention_settings(self.cfg)
            expected_log_count = int(log_count if log_count is not None else job.last_log_seq)
            expected_event_count = int(
                event_count if event_count is not None else job.last_event_seq
            )
            ensure_job_derived_row(
                conn,
                cfg=self.cfg,
                job=job,
                log_count=expected_log_count,
                event_count=expected_event_count,
                keep_tail_lines=settings.compact_tail_lines,
            )
            maybe_compact_terminal_job(
                conn,
                cfg=self.cfg,
                job=job,
                expected_log_count=expected_log_count,
                expected_event_count=expected_event_count,
            )
