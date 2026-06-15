from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias, cast

from .job_store import (
    SqliteWebJobsStore,
    event_row_from_sql,
    int_or_none,
    json_dumps,
    none_if_blank,
    read_event_frame,
    utc_now_ms,
)
from .live_event_retention import clamp_live_event_retention
from .models import EventRow, JobRecord, RollbackAuthorityRecord, VirtualEntry, WebJobsDbConfig
from .run_applied_files import derive_applied_files_from_log_text

__all__ = [
    "EventRow",
    "JobRecord",
    "VirtualEntry",
    "WebJobsDatabase",
    "WebJobsDbConfig",
    "load_web_jobs_db_config",
]


def _resolve_under_patches(patches_root: Path, rel_or_abs: str) -> Path:
    raw = str(rel_or_abs or "").strip()
    if not raw:
        return patches_root / "artifacts" / "web_jobs.sqlite3"
    path = Path(raw)
    if path.is_absolute():
        return path
    return (patches_root / path).resolve()


def _tuple_of_strings(raw: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(raw, list):
        values = cast(list[object], raw)
    elif isinstance(raw, tuple):
        values = list(cast(tuple[object, ...], raw))
    else:
        return default
    items_raw = [str(item).strip() for item in values]
    items = tuple(item for item in items_raw if item)
    return items or default


def _obj_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    raw_dict = cast(dict[object, object], value)
    out: dict[str, object] = {}
    for key, item in raw_dict.items():
        if isinstance(key, str):
            out[key] = item
    return out


def _as_int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def _as_float(value: object, default: float) -> float:
    try:
        return float(str(value))
    except Exception:
        return default


SqlParams: TypeAlias = tuple[object, ...]
EventFrameTuple: TypeAlias = tuple[str, int | None, str | None, str | None]
EventLineInsertTuple: TypeAlias = tuple[str, int, str, int | None, str | None, str | None]


def _query_one(conn: sqlite3.Connection, sql: str, params: SqlParams = ()) -> sqlite3.Row | None:
    return cast(sqlite3.Row | None, conn.execute(sql, params).fetchone())


def _query_all(conn: sqlite3.Connection, sql: str, params: SqlParams = ()) -> list[sqlite3.Row]:
    rows = cast(list[sqlite3.Row], conn.execute(sql, params).fetchall())
    return rows


def _row_value(row: sqlite3.Row, key: str | int) -> object:
    value: object = row[key]
    return value


def _row_int(row: sqlite3.Row, key: str | int, default: int = 0) -> int:
    return _as_int(_row_value(row, key), default)


def _row_str(row: sqlite3.Row, key: str | int, default: str = "") -> str:
    value = _row_value(row, key)
    return str(value if value is not None else default)


def load_web_jobs_db_config(repo_root: Path, patches_root: Path) -> WebJobsDbConfig:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    raw: dict[str, object] = {}
    if cfg_path.is_file():
        parsed: object = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        raw = _obj_dict(parsed)
    db_raw = _obj_dict(raw.get("web_jobs_db"))
    migration_raw = _obj_dict(raw.get("web_jobs_migration"))
    backup_raw = _obj_dict(raw.get("web_jobs_backup"))
    recovery_raw = _obj_dict(raw.get("web_jobs_recovery"))
    fallback_raw = _obj_dict(raw.get("web_jobs_fallback"))
    retention_raw = _obj_dict(raw.get("web_jobs_retention"))
    derived_raw = _obj_dict(raw.get("web_jobs_derived"))
    fallback_virtual_enabled = bool(
        fallback_raw.get(
            "virtual_artifacts_web_jobs_enabled",
            derived_raw.get("virtual_artifacts_web_jobs_enabled", True),
        )
    )
    derived_virtual_enabled = bool(
        derived_raw.get(
            "virtual_artifacts_web_jobs_enabled",
            fallback_raw.get("virtual_artifacts_web_jobs_enabled", True),
        )
    )
    return WebJobsDbConfig(
        db_path=_resolve_under_patches(
            patches_root,
            str(db_raw.get("path", "artifacts/web_jobs.sqlite3")),
        ),
        busy_timeout_ms=max(1, _as_int(db_raw.get("busy_timeout_ms", 5000), 5000)),
        connect_timeout_s=max(0.1, _as_float(db_raw.get("connect_timeout_s", 5.0), 5.0)),
        startup_migration_enabled=bool(migration_raw.get("startup_migration_enabled", False)),
        startup_verify_enabled=bool(migration_raw.get("startup_verify_enabled", False)),
        cleanup_enabled=bool(migration_raw.get("cleanup_enabled", False)),
        backup_destination_template=str(
            backup_raw.get(
                "destination_template",
                "artifacts/web_jobs_backup_{timestamp}.sqlite3",
            )
        ),
        backup_retain_count=max(0, _as_int(backup_raw.get("retain_count", 5), 5)),
        backup_verify_after_write=bool(backup_raw.get("verify_after_write", True)),
        backup_restore_source_preference=_tuple_of_strings(
            backup_raw.get("restore_source_preference"),
            ("explicit", "latest_backup"),
        ),
        recovery_restore_source_preference=_tuple_of_strings(
            recovery_raw.get("restore_source_preference"),
            ("explicit", "latest_backup", "main_db"),
        ),
        fallback_virtual_artifacts_web_jobs_enabled=fallback_virtual_enabled,
        derived_virtual_artifacts_web_jobs_enabled=derived_virtual_enabled,
        compatibility_enabled=fallback_virtual_enabled,
        retention_defaults={
            "jobs_keep_days": _as_int(retention_raw.get("jobs_keep_days", 30), 30),
            "logs_keep_days": _as_int(retention_raw.get("logs_keep_days", 30), 30),
            "events_keep_days": _as_int(retention_raw.get("events_keep_days", 30), 30),
        },
        retention_thresholds={
            "compact_after_jobs": _as_int(retention_raw.get("compact_after_jobs", 10000), 10000),
            "compact_after_log_lines": _as_int(
                retention_raw.get("compact_after_log_lines", 100000),
                100000,
            ),
            "compact_after_event_lines": _as_int(
                retention_raw.get("compact_after_event_lines", 100000),
                100000,
            ),
        },
    )


class WebJobsDatabase:
    def __init__(self, cfg: WebJobsDbConfig) -> None:
        self.cfg = cfg
        self._store = SqliteWebJobsStore(cfg)

    def _patches_root(self) -> Path:
        return self.cfg.db_path.parent.parent

    def connect(self) -> sqlite3.Connection:
        return self._store.connect()

    def _materialize_applied_files(
        self,
        job: JobRecord,
        *,
        log_text: str | None = None,
    ) -> JobRecord:
        if job.status != "success":
            return job
        if job.applied_files or job.applied_files_source not in {"", "unavailable"}:
            return job
        text = log_text if log_text is not None else self.read_full_log(job.job_id)
        files, source = derive_applied_files_from_log_text(
            patches_root=self._patches_root(),
            log_text=text,
        )
        job.applied_files = files
        job.applied_files_source = source
        return job

    def load_job_json(self, job_id: str) -> dict[str, object] | None:
        with self._store.connect() as conn:
            row = _query_one(
                conn,
                "SELECT * FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            )
        return None if row is None else self._store.row_to_job_json(row)

    def load_job_record(self, job_id: str) -> JobRecord | None:
        payload = self.load_job_json(job_id)
        return None if payload is None else JobRecord.from_json(payload)

    def list_job_jsons(self, *, limit: int = 200) -> list[dict[str, object]]:
        with self._store.connect() as conn:
            rows = _query_all(
                conn,
                "SELECT * FROM web_jobs ORDER BY created_unix_ms DESC, job_id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        return [self._store.row_to_job_json(row) for row in rows]

    def list_live_job_jsons(self, *, limit: int | None = None) -> list[dict[str, object]]:
        sql = (
            "SELECT * FROM web_jobs WHERE status IN ('queued', 'running') "
            "ORDER BY created_unix_ms DESC, job_id DESC"
        )
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (max(1, int(limit)),)
        with self._store.connect() as conn:
            rows = _query_all(conn, sql, params)
        return [self._store.row_to_job_json(row) for row in rows]

    def load_rollback_authority(self, job_id: str) -> RollbackAuthorityRecord | None:
        with self._store.connect() as conn:
            row = _query_one(
                conn,
                "SELECT * FROM web_job_rollback_authority WHERE job_id = ?",
                (str(job_id),),
            )
        return None if row is None else self._store.row_to_rollback_authority_record(row)

    def job_has_manifest_authority(self, job_id: str) -> bool:
        authority = self.load_rollback_authority(job_id)
        return bool(authority is not None and authority.has_manifest())

    def upsert_rollback_authority(
        self,
        authority: RollbackAuthorityRecord,
        *,
        count_as_job_change: bool = True,
    ) -> None:
        with self._store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._store.upsert_rollback_authority_row(conn, authority)
            self._store.touch_meta(conn, jobs_delta=1 if count_as_job_change else 0)
            conn.commit()

    def upsert_manifest_authority(
        self,
        job: JobRecord,
        manifest: dict[str, object],
        *,
        count_as_job_change: bool = True,
    ) -> RollbackAuthorityRecord:
        existing = self.load_rollback_authority(job.job_id)
        authority = RollbackAuthorityRecord.with_manifest(
            job_id=job.job_id,
            manifest=manifest,
            request_source_job_id=(
                existing.request_source_job_id if existing and existing.has_request() else None
            ),
            request_scope_kind=(
                existing.request_scope_kind if existing and existing.has_request() else None
            ),
            request_selected_repo_paths=(
                list(existing.request_selected_repo_paths)
                if existing and existing.has_request()
                else None
            ),
            request_preflight_token=(
                existing.request_preflight_token if existing and existing.has_request() else None
            ),
            updated_unix_ms=utc_now_ms(),
        )
        self.upsert_rollback_authority(authority, count_as_job_change=count_as_job_change)
        return authority

    def upsert_request_authority(
        self,
        *,
        job_id: str,
        source_job_id: str,
        scope_kind: str,
        selected_repo_paths: list[str],
        rollback_preflight_token: str,
        count_as_job_change: bool = True,
    ) -> RollbackAuthorityRecord:
        existing = self.load_rollback_authority(job_id)
        authority = RollbackAuthorityRecord.with_request(
            job_id=job_id,
            source_job_id=source_job_id,
            scope_kind=scope_kind,
            selected_repo_paths=selected_repo_paths,
            rollback_preflight_token=rollback_preflight_token,
            manifest_record=existing,
            updated_unix_ms=utc_now_ms(),
        )
        self.upsert_rollback_authority(authority, count_as_job_change=count_as_job_change)
        return authority

    def load_rollback_manifest(self, job_id: str) -> dict[str, object] | None:
        authority = self.load_rollback_authority(job_id)
        return None if authority is None else authority.manifest_payload()

    def load_rollback_request(self, job_id: str) -> dict[str, object] | None:
        authority = self.load_rollback_authority(job_id)
        return None if authority is None else authority.request_payload()

    def list_rollback_candidate_job_jsons(
        self,
        *,
        target_repo: str,
        created_after_unix_ms: int,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        with self._store.connect() as conn:
            rows = _query_all(
                conn,
                """
                SELECT wj.*
                  FROM web_jobs AS wj
                  JOIN web_job_rollback_authority AS ra
                    ON ra.job_id = wj.job_id
                 WHERE wj.status = ?
                   AND wj.effective_runner_target_repo = ?
                   AND wj.created_unix_ms > ?
                   AND ra.authority_role IN ('manifest', 'manifest_and_request')
                 ORDER BY wj.created_unix_ms DESC, wj.job_id DESC
                 LIMIT ?
                """,
                (
                    "success",
                    str(target_repo),
                    int(created_after_unix_ms),
                    max(1, int(limit)),
                ),
            )
        return [self._store.row_to_job_json(row) for row in rows]

    def jobs_signature(self) -> tuple[int, int]:
        with self._store.connect() as conn:
            meta = _query_one(conn, "SELECT jobs_rev FROM web_jobs_meta WHERE singleton = 1")
            count_row = _query_one(conn, "SELECT COUNT(*) FROM web_jobs")
        rev = _row_int(meta, "jobs_rev") if meta is not None else 0
        count = _row_int(count_row, 0) if count_row is not None else 0
        return count, rev

    def load_job_stats_summary(self) -> dict[str, int]:
        with self._store.connect() as conn:
            row = _query_one(
                conn,
                """
                SELECT
                    jobs_total,
                    success_total,
                    fail_total,
                    canceled_total,
                    unknown_total,
                    updated_unix_ms
                  FROM web_jobs_stats
                 WHERE singleton = 1
                """,
            )
        if row is None:
            return {
                "jobs_total": 0,
                "success_total": 0,
                "fail_total": 0,
                "canceled_total": 0,
                "unknown_total": 0,
                "updated_unix_ms": 0,
            }
        return {
            "jobs_total": _row_int(row, "jobs_total"),
            "success_total": _row_int(row, "success_total"),
            "fail_total": _row_int(row, "fail_total"),
            "canceled_total": _row_int(row, "canceled_total"),
            "unknown_total": _row_int(row, "unknown_total"),
            "updated_unix_ms": _row_int(row, "updated_unix_ms"),
        }

    def upsert_job(self, job: JobRecord, *, count_as_job_change: bool = True) -> None:
        job = self._materialize_applied_files(job)
        with self._store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _query_one(
                conn,
                "SELECT row_rev, last_log_seq, last_event_seq FROM web_jobs WHERE job_id = ?",
                (str(job.job_id),),
            )
            row_rev = (_row_int(row, "row_rev") if row is not None else 0) + 1
            log_count = max(
                int(job.last_log_seq or 0),
                _row_int(row, "last_log_seq") if row is not None else 0,
            )
            event_count = max(
                int(job.last_event_seq or 0),
                _row_int(row, "last_event_seq") if row is not None else 0,
            )
            self._store.upsert_job_row(
                conn,
                job,
                log_count=log_count,
                event_count=event_count,
                row_rev=row_rev,
            )
            self._store.touch_meta(conn, jobs_delta=1 if count_as_job_change else 0)
            conn.commit()

    def replace_job_history(
        self,
        job: JobRecord,
        *,
        log_lines: list[str],
        event_lines: list[str],
    ) -> None:
        job = self._materialize_applied_files(job, log_text="\n".join(log_lines))
        with self._store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row_rev = self._store.current_row_rev(conn, job.job_id) + 1
            self._store.upsert_job_row(
                conn,
                job,
                log_count=len(log_lines),
                event_count=len(event_lines),
                row_rev=row_rev,
            )
            conn.execute("DELETE FROM web_job_log_lines WHERE job_id = ?", (str(job.job_id),))
            conn.execute("DELETE FROM web_job_event_lines WHERE job_id = ?", (str(job.job_id),))
            if log_lines:
                conn.executemany(
                    "INSERT INTO web_job_log_lines(job_id, seq, line) VALUES (?, ?, ?)",
                    [(str(job.job_id), idx + 1, str(line)) for idx, line in enumerate(log_lines)],
                )
            if event_lines:
                items: list[EventLineInsertTuple] = []
                for idx, raw_line in enumerate(event_lines, start=1):
                    text = str(raw_line).rstrip("\n")
                    parsed = read_event_frame(text)
                    items.append(
                        (
                            str(job.job_id),
                            idx,
                            text,
                            int_or_none(parsed.get("seq")) if parsed is not None else None,
                            none_if_blank(parsed.get("type")) if parsed is not None else None,
                            none_if_blank(parsed.get("event")) if parsed is not None else None,
                        )
                    )
                conn.executemany(
                    """
                    INSERT INTO web_job_event_lines(
                        job_id, seq, raw_line, ipc_seq, frame_type, frame_event
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    items,
                )
            self._store.touch_meta(
                conn,
                jobs_delta=1,
                logs_delta=len(log_lines),
                events_delta=len(event_lines),
            )
            conn.commit()

    def update_applied_files(self, job_id: str, files: list[str], source: str) -> None:
        with self._store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row_rev = self._store.current_row_rev(conn, str(job_id)) + 1
            conn.execute(
                """
                UPDATE web_jobs
                   SET applied_files_json = ?,
                       applied_files_source = ?,
                       row_rev = ?
                 WHERE job_id = ?
                """,
                (json_dumps(list(files)), str(source), row_rev, str(job_id)),
            )
            self._store.touch_meta(conn, jobs_delta=1)
            conn.commit()

    def mark_orphaned(self, job_id: str) -> JobRecord | None:
        job = self.load_job_record(job_id)
        if job is None:
            return None
        if job.status not in {"queued", "running"}:
            return job
        job.status = "fail"
        if not job.ended_utc:
            job.ended_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        job.error = "orphaned: not in memory queue"
        self.upsert_job(job)
        return job

    def append_log_line(self, job_id: str, line: str) -> int:
        text = str(line or "")
        with self._store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _query_one(
                conn,
                "SELECT last_log_seq, row_rev FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            )
            if row is None:
                conn.rollback()
                return 0
            seq = _row_int(row, "last_log_seq") + 1
            row_rev = _row_int(row, "row_rev") + 1
            conn.execute(
                "INSERT INTO web_job_log_lines(job_id, seq, line) VALUES (?, ?, ?)",
                (str(job_id), seq, text),
            )
            conn.execute(
                "UPDATE web_jobs SET last_log_seq = ?, row_rev = ? WHERE job_id = ?",
                (seq, row_rev, str(job_id)),
            )
            self._store.touch_meta(conn, logs_delta=1)
            conn.commit()
        return seq

    def append_event_line(self, job_id: str, raw_line: str) -> int:
        text = str(raw_line or "").rstrip("\n")
        parsed = read_event_frame(text)
        ipc_seq = int_or_none(parsed.get("seq")) if parsed is not None else None
        frame_type = none_if_blank(parsed.get("type")) if parsed is not None else None
        frame_event = none_if_blank(parsed.get("event")) if parsed is not None else None
        with self._store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _query_one(
                conn,
                "SELECT last_event_seq, row_rev FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            )
            if row is None:
                conn.rollback()
                return 0
            seq = _row_int(row, "last_event_seq") + 1
            row_rev = _row_int(row, "row_rev") + 1
            conn.execute(
                """
                INSERT INTO web_job_event_lines(
                    job_id, seq, raw_line, ipc_seq, frame_type, frame_event
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(job_id), seq, text, ipc_seq, frame_type, frame_event),
            )
            conn.execute(
                "UPDATE web_jobs SET last_event_seq = ?, row_rev = ? WHERE job_id = ?",
                (seq, row_rev, str(job_id)),
            )
            self._store.touch_meta(conn, events_delta=1)
            conn.commit()
        return seq

    def append_event_lines(self, job_id: str, raw_lines: list[str]) -> int:
        items: list[EventFrameTuple] = []
        for raw_line in raw_lines:
            text = str(raw_line or "").rstrip("\n")
            parsed = read_event_frame(text)
            items.append(
                (
                    text,
                    int_or_none(parsed.get("seq")) if parsed is not None else None,
                    none_if_blank(parsed.get("type")) if parsed is not None else None,
                    none_if_blank(parsed.get("event")) if parsed is not None else None,
                )
            )
        if not items:
            return 0
        with self._store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _query_one(
                conn,
                "SELECT last_event_seq, row_rev FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            )
            if row is None:
                conn.rollback()
                return 0
            base_seq = _row_int(row, "last_event_seq")
            row_rev = _row_int(row, "row_rev") + len(items)
            seq_items: list[EventLineInsertTuple] = [
                (str(job_id), base_seq + idx, text, ipc_seq, frame_type, frame_event)
                for idx, (text, ipc_seq, frame_type, frame_event) in enumerate(items, start=1)
            ]
            conn.executemany(
                """
                INSERT INTO web_job_event_lines(
                    job_id, seq, raw_line, ipc_seq, frame_type, frame_event
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                seq_items,
            )
            final_seq = base_seq + len(seq_items)
            conn.execute(
                "UPDATE web_jobs SET last_event_seq = ?, row_rev = ? WHERE job_id = ?",
                (final_seq, row_rev, str(job_id)),
            )
            self._store.touch_meta(conn, events_delta=len(seq_items))
            conn.commit()
        return final_seq

    def _read_raw_log_tail(self, job_id: str, *, lines: int = 200) -> str:
        limit = max(1, min(int(lines), 5000))
        with self._store.connect() as conn:
            rows = _query_all(
                conn,
                """
                SELECT line FROM web_job_log_lines
                 WHERE job_id = ?
                 ORDER BY seq DESC
                 LIMIT ?
                """,
                (str(job_id), limit),
            )
        return "\n".join(_row_str(row, "line") for row in reversed(rows))

    def read_raw_log_tail(self, job_id: str, *, lines: int = 200) -> str:
        return self._read_raw_log_tail(job_id, lines=lines)

    def read_log_tail(self, job_id: str, *, lines: int = 200) -> str:
        from .web_jobs_derived import read_effective_log_tail

        return read_effective_log_tail(self, job_id, lines=lines)

    def _read_raw_full_log(self, job_id: str) -> str:
        with self._store.connect() as conn:
            rows = _query_all(
                conn,
                "SELECT line FROM web_job_log_lines WHERE job_id = ? ORDER BY seq ASC",
                (str(job_id),),
            )
        return "\n".join(_row_str(row, "line") for row in rows)

    def read_raw_full_log(self, job_id: str) -> str:
        return self._read_raw_full_log(job_id)

    def read_full_log(self, job_id: str) -> str:
        from .web_jobs_derived import read_effective_full_log

        return read_effective_full_log(self, job_id)

    def read_event_rows(
        self,
        job_id: str,
        *,
        after_seq: int = 0,
        limit: int = 2000,
    ) -> list[EventRow]:
        with self._store.connect() as conn:
            rows = _query_all(
                conn,
                """
                SELECT seq, raw_line, ipc_seq, frame_type, frame_event
                  FROM web_job_event_lines
                 WHERE job_id = ? AND seq > ?
                 ORDER BY seq ASC
                 LIMIT ?
                """,
                (str(job_id), int(after_seq), max(1, int(limit))),
            )
        return [event_row_from_sql(row) for row in rows]

    def read_event_tail(self, job_id: str, *, lines: int = 500) -> tuple[list[EventRow], int]:
        limit = clamp_live_event_retention(lines)
        with self._store.connect() as conn:
            rows = _query_all(
                conn,
                """
                SELECT seq, raw_line, ipc_seq, frame_type, frame_event
                  FROM web_job_event_lines
                 WHERE job_id = ?
                 ORDER BY seq DESC
                 LIMIT ?
                """,
                (str(job_id), limit),
            )
        items = [event_row_from_sql(row) for row in reversed(rows)]
        return items, (items[-1].seq if items else 0)

    def last_event_seq(self, job_id: str) -> int:
        with self._store.connect() as conn:
            row = _query_one(
                conn,
                "SELECT last_event_seq FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            )
        return _row_int(row, "last_event_seq") if row is not None else 0

    def legacy_job_json_text(self, job_id: str) -> str | None:
        payload = self.load_job_json(job_id)
        if payload is None:
            return None
        return json.dumps(payload, ensure_ascii=True, indent=2)

    def legacy_event_filename(self, job_id: str) -> str:
        payload = self.load_job_json(job_id) or {}
        mode = str(payload.get("mode", ""))
        issue_id = str(payload.get("issue_id", ""))
        if mode in {"finalize_live", "finalize_workspace"}:
            return "am_patch_finalize.jsonl"
        if issue_id.isdigit():
            return f"am_patch_issue_{issue_id}.jsonl"
        return "am_patch_finalize.jsonl"

    def read_effective_event_tail_text(self, job_id: str, *, lines: int = 500) -> str:
        from .web_jobs_derived import read_effective_event_tail_text

        return read_effective_event_tail_text(self, job_id, lines=lines)

    def read_effective_event_text(self, job_id: str) -> str:
        from .web_jobs_derived import read_effective_full_event_text

        return read_effective_full_event_text(self, job_id)

    def legacy_event_text(self, job_id: str) -> str:
        return self.read_effective_event_text(job_id)

    def list_job_ids(self, *, limit: int = 2000) -> list[str]:
        with self._store.connect() as conn:
            rows = _query_all(
                conn,
                "SELECT job_id FROM web_jobs ORDER BY created_unix_ms DESC, job_id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        return [_row_str(row, "job_id") for row in rows]

    def export_legacy_tree(self, dest_root: Path) -> None:
        for job_id in self.list_job_ids(limit=1_000_000):
            job_dir = dest_root / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            job_text = self.legacy_job_json_text(job_id)
            if job_text is not None:
                (job_dir / "job.json").write_text(job_text + "\n", encoding="utf-8")
            (job_dir / "runner.log").write_text(self.read_full_log(job_id), encoding="utf-8")
            (job_dir / self.legacy_event_filename(job_id)).write_text(
                self.legacy_event_text(job_id),
                encoding="utf-8",
            )

    def create_backup(self, *, destination_template: str | None = None) -> Path:
        template = str(destination_template or self.cfg.backup_destination_template)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_root = self.cfg.db_path.parent.parent
        dst = (backup_root / template.format(timestamp=timestamp)).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        with self._store.connect() as src_conn:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            with sqlite3.connect(str(dst)) as dst_conn:
                src_conn.backup(dst_conn)
        if self.cfg.backup_verify_after_write:
            with sqlite3.connect(str(dst)) as verify_conn:
                verify_conn.execute("PRAGMA quick_check")
        self._prune_backups(dst.parent, template)
        return dst

    def _prune_backups(self, backup_dir: Path, template: str) -> None:
        keep = int(self.cfg.backup_retain_count)
        if keep <= 0:
            return
        stem = Path(template).name.split("{timestamp}")[0]
        candidates: list[Path] = [
            path for path in backup_dir.iterdir() if path.is_file() and path.name.startswith(stem)
        ]

        def _mtime_key(path: Path) -> int:
            return int(path.stat().st_mtime_ns)

        candidates.sort(key=_mtime_key, reverse=True)
        for path in candidates[keep:]:
            path.unlink(missing_ok=True)

    def restore_backup(self, source: Path) -> None:
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=self.cfg.db_path.name + ".restore.",
            dir=str(self.cfg.db_path.parent),
        )
        os.close(tmp_fd)
        Path(tmp_name).unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(self.cfg.db_path) + suffix).unlink(missing_ok=True)
        try:
            shutil.copy2(source, tmp_name)
            Path(tmp_name).replace(self.cfg.db_path)
        finally:
            Path(tmp_name).unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(self.cfg.db_path) + suffix).unlink(missing_ok=True)
        self._store.init_db()
