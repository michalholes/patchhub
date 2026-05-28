from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Protocol, TypeAlias, cast, runtime_checkable

from .models import (
    EventRow,
    JobRecord,
    RollbackAuthorityRecord,
    RollbackAuthorityRole,
    WebJobsDbConfig,
)

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
    run_start_sha TEXT,
    run_end_sha TEXT,
    revert_source_job_id TEXT,
    rollback_source_job_id TEXT,
    rollback_scope_manifest_rel_path TEXT,
    rollback_scope_manifest_hash TEXT,
    rollback_authority_kind TEXT,
    rollback_authority_source_ref TEXT,
    origin_backend_mode TEXT,
    origin_authoritative_backend TEXT,
    origin_backend_session_id TEXT,
    origin_recovery_json TEXT,
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
CREATE TABLE IF NOT EXISTS web_job_rollback_authority (
    job_id TEXT PRIMARY KEY,
    authority_role TEXT NOT NULL,
    manifest_version INTEGER,
    manifest_source_job_id TEXT,
    manifest_issue_id TEXT,
    manifest_selected_target_repo_token TEXT,
    manifest_effective_runner_target_repo TEXT,
    manifest_authority_kind TEXT,
    manifest_authority_source_ref TEXT,
    manifest_entries_json TEXT NOT NULL DEFAULT '[]',
    request_source_job_id TEXT,
    request_scope_kind TEXT,
    request_selected_repo_paths_json TEXT NOT NULL DEFAULT '[]',
    request_preflight_token TEXT,
    updated_unix_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS web_jobs_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    jobs_rev INTEGER NOT NULL,
    logs_rev INTEGER NOT NULL,
    events_rev INTEGER NOT NULL,
    updated_unix_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS run_stats_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_indexed_mtime_ns INTEGER NOT NULL DEFAULT 0,
    last_indexed_filename TEXT NOT NULL DEFAULT '',
    all_time_total INTEGER NOT NULL DEFAULT 0,
    all_time_success INTEGER NOT NULL DEFAULT 0,
    all_time_fail INTEGER NOT NULL DEFAULT 0,
    all_time_unknown INTEGER NOT NULL DEFAULT 0,
    updated_unix_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_stats_seen (
    source_key TEXT PRIMARY KEY,
    log_rel_path TEXT NOT NULL,
    log_mtime_ns INTEGER NOT NULL,
    log_size INTEGER NOT NULL DEFAULT 0,
    run_unix_ms INTEGER NOT NULL,
    result TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_stats_seen_run_unix_ms
    ON run_stats_seen(run_unix_ms);
CREATE INDEX IF NOT EXISTS idx_run_stats_seen_log_mtime_ns
    ON run_stats_seen(log_mtime_ns, log_rel_path);
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
CREATE INDEX IF NOT EXISTS idx_web_job_rollback_authority_manifest_repo
    ON web_job_rollback_authority(
        manifest_effective_runner_target_repo,
        updated_unix_ms DESC,
        job_id DESC
    );
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


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _none_if_blank(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _rollback_authority_role(value: object) -> RollbackAuthorityRole:
    text = str(value or "").strip()
    if text == "manifest":
        return "manifest"
    if text == "request":
        return "request"
    if text == "manifest_and_request":
        return "manifest_and_request"
    raise ValueError(f"invalid rollback authority role: {text}")


def _obj_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw_dict = cast(dict[object, object], value)
    out: dict[str, object] = {}
    for key, item in raw_dict.items():
        if isinstance(key, str):
            out[key] = item
    return out


def _json_loads_obj(text: str) -> object:
    parsed: object = json.loads(text)
    return parsed


SqlParams: TypeAlias = tuple[object, ...]


@runtime_checkable
class _RowLike(Protocol):
    def keys(self) -> object: ...

    def __getitem__(self, key: object, /) -> object: ...


def _row_dict(value: object) -> dict[str, object]:
    row = _obj_dict(value)
    if row is not None:
        return row
    if not isinstance(value, _RowLike):
        return {}
    out: dict[str, object] = {}
    keys_raw = value.keys()
    keys: list[object]
    if isinstance(keys_raw, list):
        keys = list(cast(list[object], keys_raw))
    elif isinstance(keys_raw, tuple):
        keys = list(cast(tuple[object, ...], keys_raw))
    else:
        return {}
    for key_obj in keys:
        key = str(key_obj)
        out[key] = value[key]
    return out


def _as_int(value: object, default: int = 0) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else default


def _query_one_dict(
    conn: sqlite3.Connection,
    sql: str,
    params: SqlParams = (),
) -> dict[str, object]:
    row_obj = cast(object, conn.execute(sql, params).fetchone())
    return _row_dict(row_obj)


def _sqlite_row_factory(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> object:
    return sqlite3.Row(cursor, row)


def _read_event_frame(text: str) -> dict[str, object] | None:
    try:
        parsed = _json_loads_obj(text)
    except Exception:
        return None
    return _obj_dict(parsed)


_WEB_JOBS_ADDITIVE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("commit_message", "TEXT"),
    ("zip_target_repo", "TEXT"),
    ("selected_target_repo", "TEXT"),
    ("effective_runner_target_repo", "TEXT"),
    ("target_mismatch", "INTEGER NOT NULL DEFAULT 0"),
    ("run_start_sha", "TEXT"),
    ("run_end_sha", "TEXT"),
    ("revert_source_job_id", "TEXT"),
    ("rollback_source_job_id", "TEXT"),
    ("rollback_scope_manifest_rel_path", "TEXT"),
    ("rollback_scope_manifest_hash", "TEXT"),
    ("rollback_authority_kind", "TEXT"),
    ("rollback_authority_source_ref", "TEXT"),
    ("origin_backend_mode", "TEXT"),
    ("origin_authoritative_backend", "TEXT"),
    ("origin_backend_session_id", "TEXT"),
    ("origin_recovery_json", "TEXT"),
)


def _ensure_web_jobs_additive_columns(conn: sqlite3.Connection) -> None:
    rows_obj = cast(object, conn.execute("PRAGMA table_info(web_jobs)").fetchall())
    rows = cast(list[object], rows_obj) if isinstance(rows_obj, list) else []
    existing: set[str] = set()
    for row in rows:
        row_dict = _row_dict(row)
        name = row_dict.get("name")
        if name is not None:
            existing.add(str(name))
            continue
        if isinstance(row, tuple):
            row_tuple = cast(tuple[object, ...], row)
            if len(row_tuple) > 1:
                existing.add(str(row_tuple[1]))
    for name, ddl in _WEB_JOBS_ADDITIVE_COLUMNS:
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE web_jobs ADD COLUMN {name} {ddl}")
        existing.add(name)


def _event_row_from_sql(row: sqlite3.Row) -> EventRow:
    payload = _row_dict(row)
    return EventRow(
        seq=_as_int(payload.get("seq"), 0),
        raw_line=str(payload.get("raw_line", "")),
        ipc_seq=_int_or_none(payload.get("ipc_seq")),
        frame_type=_none_if_blank(payload.get("frame_type")),
        frame_event=_none_if_blank(payload.get("frame_event")),
    )


def utc_now_ms() -> int:
    return _utc_now_ms()


def int_or_none(value: object) -> int | None:
    return _int_or_none(value)


def json_dumps(value: object) -> str:
    return _json_dumps(value)


def none_if_blank(value: object) -> str | None:
    return _none_if_blank(value)


def read_event_frame(text: str) -> dict[str, object] | None:
    return _read_event_frame(text)


def event_row_from_sql(row: sqlite3.Row) -> EventRow:
    return _event_row_from_sql(row)


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
        conn.row_factory = _sqlite_row_factory
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(f"PRAGMA busy_timeout={int(self.cfg.busy_timeout_ms)}")
        return conn

    def connect(self) -> sqlite3.Connection:
        return self._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.executescript(_SCHEMA)
            _ensure_web_jobs_additive_columns(conn)
            auto_vacuum_row = _query_one_dict(conn, "PRAGMA auto_vacuum")
            auto_vacuum = _as_int(auto_vacuum_row.get("auto_vacuum"), 0)
            if auto_vacuum <= 0:
                raw_row = cast(object, conn.execute("PRAGMA auto_vacuum").fetchone())
                if isinstance(raw_row, tuple) and raw_row:
                    raw_tuple = cast(tuple[object, ...], raw_row)
                    auto_vacuum = _as_int(raw_tuple[0], 0)
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
                INSERT INTO run_stats_meta(
                    singleton,
                    last_indexed_mtime_ns,
                    last_indexed_filename,
                    all_time_total,
                    all_time_success,
                    all_time_fail,
                    all_time_unknown,
                    updated_unix_ms
                ) VALUES(1, 0, '', 0, 0, 0, 0, ?)
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

    def init_db(self) -> None:
        self._init_db()

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

    def touch_meta(
        self,
        conn: sqlite3.Connection,
        *,
        jobs_delta: int = 0,
        logs_delta: int = 0,
        events_delta: int = 0,
    ) -> None:
        self._touch_meta(
            conn,
            jobs_delta=jobs_delta,
            logs_delta=logs_delta,
            events_delta=events_delta,
        )

    def _row_to_job_json(self, row: sqlite3.Row) -> dict[str, object]:
        payload_row = _row_dict(row)
        row_keys = set(payload_row.keys())
        rollback_source_job_id = (
            payload_row.get("rollback_source_job_id")
            if "rollback_source_job_id" in row_keys
            and payload_row.get("rollback_source_job_id") is not None
            else (
                payload_row.get("revert_source_job_id")
                if "revert_source_job_id" in row_keys
                and payload_row.get("revert_source_job_id") is not None
                else None
            )
        )
        payload: dict[str, object] = {
            "job_id": str(payload_row.get("job_id", "")),
            "created_utc": str(payload_row.get("created_utc", "")),
            "created_unix_ms": _as_int(payload_row.get("created_unix_ms"), 0),
            "mode": str(payload_row.get("mode", "")),
            "issue_id": str(payload_row.get("issue_id_raw", "")),
            "commit_summary": str(payload_row.get("commit_summary", "")),
            "commit_message": payload_row.get("commit_message"),
            "patch_basename": payload_row.get("patch_basename"),
            "raw_command": str(payload_row.get("raw_command", "")),
            "canonical_command": _json_loads_obj(
                str(payload_row.get("canonical_command_json", "[]"))
            ),
            "status": str(payload_row.get("status", "")),
            "started_utc": payload_row.get("started_utc"),
            "ended_utc": payload_row.get("ended_utc"),
            "return_code": payload_row.get("return_code"),
            "error": payload_row.get("error"),
            "cancel_requested_utc": payload_row.get("cancel_requested_utc"),
            "cancel_ack_utc": payload_row.get("cancel_ack_utc"),
            "cancel_source": payload_row.get("cancel_source"),
            "original_patch_path": payload_row.get("original_patch_path"),
            "effective_patch_path": payload_row.get("effective_patch_path"),
            "effective_patch_kind": payload_row.get("effective_patch_kind"),
            "selected_patch_entries": _json_loads_obj(
                str(payload_row.get("selected_patch_entries_json", "[]"))
            ),
            "selected_repo_paths": _json_loads_obj(
                str(payload_row.get("selected_repo_paths_json", "[]"))
            ),
            "zip_target_repo": payload_row.get("zip_target_repo"),
            "selected_target_repo": payload_row.get("selected_target_repo"),
            "effective_runner_target_repo": payload_row.get("effective_runner_target_repo"),
            "target_mismatch": bool(payload_row.get("target_mismatch")),
            "run_start_sha": payload_row.get("run_start_sha"),
            "run_end_sha": payload_row.get("run_end_sha"),
            "revert_source_job_id": rollback_source_job_id,
            "rollback_source_job_id": rollback_source_job_id,
            "rollback_scope_manifest_rel_path": payload_row.get("rollback_scope_manifest_rel_path"),
            "rollback_scope_manifest_hash": payload_row.get("rollback_scope_manifest_hash"),
            "rollback_authority_kind": payload_row.get("rollback_authority_kind"),
            "rollback_authority_source_ref": payload_row.get("rollback_authority_source_ref"),
            "applied_files": _json_loads_obj(str(payload_row.get("applied_files_json", "[]"))),
            "applied_files_source": str(payload_row.get("applied_files_source", "unavailable")),
            "last_log_seq": _as_int(payload_row.get("last_log_seq"), 0),
            "last_event_seq": _as_int(payload_row.get("last_event_seq"), 0),
            "row_rev": _as_int(payload_row.get("row_rev"), 0),
        }
        if payload_row.get("origin_backend_mode") is not None:
            payload["origin_backend_mode"] = payload_row.get("origin_backend_mode")
        if payload_row.get("origin_authoritative_backend") is not None:
            payload["origin_authoritative_backend"] = payload_row.get(
                "origin_authoritative_backend"
            )
        if payload_row.get("origin_backend_session_id") is not None:
            payload["origin_backend_session_id"] = payload_row.get("origin_backend_session_id")
        if payload_row.get("origin_recovery_json") is not None:
            payload["origin_recovery_json"] = payload_row.get("origin_recovery_json")
        return payload

    def row_to_job_json(self, row: sqlite3.Row) -> dict[str, object]:
        return self._row_to_job_json(row)

    def _row_to_rollback_authority_record(self, row: sqlite3.Row) -> RollbackAuthorityRecord:
        payload = _row_dict(row)
        return RollbackAuthorityRecord(
            job_id=str(payload.get("job_id", "")),
            authority_role=_rollback_authority_role(payload.get("authority_role")),
            manifest_version=_int_or_none(payload.get("manifest_version")),
            manifest_source_job_id=_none_if_blank(payload.get("manifest_source_job_id")),
            manifest_issue_id=_none_if_blank(payload.get("manifest_issue_id")),
            manifest_selected_target_repo_token=_none_if_blank(
                payload.get("manifest_selected_target_repo_token")
            ),
            manifest_effective_runner_target_repo=_none_if_blank(
                payload.get("manifest_effective_runner_target_repo")
            ),
            manifest_authority_kind=_none_if_blank(payload.get("manifest_authority_kind")),
            manifest_authority_source_ref=_none_if_blank(
                payload.get("manifest_authority_source_ref")
            ),
            manifest_entries=cast(
                list[dict[str, object]],
                _json_loads_obj(str(payload.get("manifest_entries_json") or "[]")),
            ),
            request_source_job_id=_none_if_blank(payload.get("request_source_job_id")),
            request_scope_kind=_none_if_blank(payload.get("request_scope_kind")),
            request_selected_repo_paths=cast(
                list[str],
                _json_loads_obj(str(payload.get("request_selected_repo_paths_json") or "[]")),
            ),
            request_preflight_token=_none_if_blank(payload.get("request_preflight_token")),
            updated_unix_ms=_as_int(payload.get("updated_unix_ms"), 0),
        )

    def row_to_rollback_authority_record(self, row: sqlite3.Row) -> RollbackAuthorityRecord:
        return self._row_to_rollback_authority_record(row)

    def _rollback_authority_values(self, authority: RollbackAuthorityRecord) -> tuple[object, ...]:
        return (
            authority.job_id,
            authority.authority_role,
            authority.manifest_version,
            authority.manifest_source_job_id,
            authority.manifest_issue_id,
            authority.manifest_selected_target_repo_token,
            authority.manifest_effective_runner_target_repo,
            authority.manifest_authority_kind,
            authority.manifest_authority_source_ref,
            _json_dumps(list(authority.manifest_entries)),
            authority.request_source_job_id,
            authority.request_scope_kind,
            _json_dumps(list(authority.request_selected_repo_paths)),
            authority.request_preflight_token,
            int(authority.updated_unix_ms or 0),
        )

    def _upsert_rollback_authority_row(
        self,
        conn: sqlite3.Connection,
        authority: RollbackAuthorityRecord,
    ) -> None:
        conn.execute(
            """
            INSERT INTO web_job_rollback_authority(
                job_id, authority_role, manifest_version, manifest_source_job_id,
                manifest_issue_id, manifest_selected_target_repo_token,
                manifest_effective_runner_target_repo, manifest_authority_kind,
                manifest_authority_source_ref, manifest_entries_json,
                request_source_job_id, request_scope_kind,
                request_selected_repo_paths_json, request_preflight_token,
                updated_unix_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                authority_role = excluded.authority_role,
                manifest_version = excluded.manifest_version,
                manifest_source_job_id = excluded.manifest_source_job_id,
                manifest_issue_id = excluded.manifest_issue_id,
                manifest_selected_target_repo_token = excluded.manifest_selected_target_repo_token,
                manifest_effective_runner_target_repo =
                    excluded.manifest_effective_runner_target_repo,
                manifest_authority_kind = excluded.manifest_authority_kind,
                manifest_authority_source_ref = excluded.manifest_authority_source_ref,
                manifest_entries_json = excluded.manifest_entries_json,
                request_source_job_id = excluded.request_source_job_id,
                request_scope_kind = excluded.request_scope_kind,
                request_selected_repo_paths_json = excluded.request_selected_repo_paths_json,
                request_preflight_token = excluded.request_preflight_token,
                updated_unix_ms = excluded.updated_unix_ms
            """,
            self._rollback_authority_values(authority),
        )

    def upsert_rollback_authority_row(
        self,
        conn: sqlite3.Connection,
        authority: RollbackAuthorityRecord,
    ) -> None:
        self._upsert_rollback_authority_row(conn, authority)

    def _current_row_rev(self, conn: sqlite3.Connection, job_id: str) -> int:
        row = _query_one_dict(
            conn,
            "SELECT row_rev FROM web_jobs WHERE job_id = ?",
            (job_id,),
        )
        return _as_int(row.get("row_rev"), 0)

    def current_row_rev(self, conn: sqlite3.Connection, job_id: str) -> int:
        return self._current_row_rev(conn, job_id)

    def _job_values(
        self,
        job: JobRecord,
        *,
        log_count: int | None = None,
        event_count: int | None = None,
        row_rev: int,
    ) -> tuple[object, ...]:
        payload = job.to_json()
        created_unix_ms = _int_or_none(payload.get("created_unix_ms"))
        return (
            job.job_id,
            str(payload.get("created_utc", "")),
            int(
                created_unix_ms if created_unix_ms is not None else _utc_to_unix_ms(job.created_utc)
            ),
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
            job.run_start_sha,
            job.run_end_sha,
            job.revert_source_job_id or job.rollback_source_job_id,
            job.rollback_source_job_id or job.revert_source_job_id,
            job.rollback_scope_manifest_rel_path,
            job.rollback_scope_manifest_hash,
            job.rollback_authority_kind,
            job.rollback_authority_source_ref,
            job.origin_backend_mode,
            job.origin_authoritative_backend,
            job.origin_backend_session_id,
            job.origin_recovery_json,
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
                run_start_sha, run_end_sha, revert_source_job_id,
                rollback_source_job_id, rollback_scope_manifest_rel_path,
                rollback_scope_manifest_hash, rollback_authority_kind,
                rollback_authority_source_ref, origin_backend_mode,
                origin_authoritative_backend, origin_backend_session_id,
                origin_recovery_json, applied_files_json, applied_files_source,
                last_log_seq, last_event_seq, row_rev
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
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
                run_start_sha = excluded.run_start_sha,
                run_end_sha = excluded.run_end_sha,
                revert_source_job_id = excluded.revert_source_job_id,
                rollback_source_job_id = excluded.rollback_source_job_id,
                rollback_scope_manifest_rel_path = excluded.rollback_scope_manifest_rel_path,
                rollback_scope_manifest_hash = excluded.rollback_scope_manifest_hash,
                rollback_authority_kind = excluded.rollback_authority_kind,
                rollback_authority_source_ref = excluded.rollback_authority_source_ref,
                origin_backend_mode = excluded.origin_backend_mode,
                origin_authoritative_backend = excluded.origin_authoritative_backend,
                origin_backend_session_id = excluded.origin_backend_session_id,
                origin_recovery_json = excluded.origin_recovery_json,
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

    def upsert_job_row(
        self,
        conn: sqlite3.Connection,
        job: JobRecord,
        *,
        log_count: int | None = None,
        event_count: int | None = None,
        row_rev: int,
    ) -> None:
        self._upsert_job_row(
            conn,
            job,
            log_count=log_count,
            event_count=event_count,
            row_rev=row_rev,
        )
