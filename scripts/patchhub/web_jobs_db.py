from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .job_store import (
    SqliteWebJobsStore,
    _event_row_from_sql,
    _int_or_none,
    _json_dumps,
    _none_if_blank,
    _read_event_frame,
)
from .live_event_retention import clamp_live_event_retention
from .models import EventRow, JobRecord, VirtualEntry, WebJobsDbConfig
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


def _tuple_of_strings(raw: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        return default
    items = tuple(str(item).strip() for item in raw if str(item).strip())
    return items or default


def load_web_jobs_db_config(repo_root: Path, patches_root: Path) -> WebJobsDbConfig:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    raw: dict[str, Any] = {}
    if cfg_path.is_file():
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    db_raw = raw.get("web_jobs_db", {})
    migration_raw = raw.get("web_jobs_migration", {})
    backup_raw = raw.get("web_jobs_backup", {})
    recovery_raw = raw.get("web_jobs_recovery", {})
    fallback_raw = raw.get("web_jobs_fallback", {})
    retention_raw = raw.get("web_jobs_retention", {})
    derived_raw = raw.get("web_jobs_derived", {})
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
        busy_timeout_ms=max(1, int(db_raw.get("busy_timeout_ms", 5000))),
        connect_timeout_s=max(0.1, float(db_raw.get("connect_timeout_s", 5.0))),
        startup_migration_enabled=bool(migration_raw.get("startup_migration_enabled", False)),
        startup_verify_enabled=bool(migration_raw.get("startup_verify_enabled", False)),
        cleanup_enabled=bool(migration_raw.get("cleanup_enabled", False)),
        backup_destination_template=str(
            backup_raw.get(
                "destination_template",
                "artifacts/web_jobs_backup_{timestamp}.sqlite3",
            )
        ),
        backup_retain_count=max(0, int(backup_raw.get("retain_count", 5))),
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
            "jobs_keep_days": int(retention_raw.get("jobs_keep_days", 30)),
            "logs_keep_days": int(retention_raw.get("logs_keep_days", 30)),
            "events_keep_days": int(retention_raw.get("events_keep_days", 30)),
        },
        retention_thresholds={
            "compact_after_jobs": int(retention_raw.get("compact_after_jobs", 10000)),
            "compact_after_log_lines": int(retention_raw.get("compact_after_log_lines", 100000)),
            "compact_after_event_lines": int(
                retention_raw.get("compact_after_event_lines", 100000)
            ),
        },
    )


class WebJobsDatabase:
    def __init__(self, cfg: WebJobsDbConfig) -> None:
        self.cfg = cfg
        self._store = SqliteWebJobsStore(cfg)

    def _patches_root(self) -> Path:
        return self.cfg.db_path.parent.parent

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

    def load_job_json(self, job_id: str) -> dict[str, Any] | None:
        with self._store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        return None if row is None else self._store._row_to_job_json(row)

    def load_job_record(self, job_id: str) -> JobRecord | None:
        payload = self.load_job_json(job_id)
        return None if payload is None else JobRecord.from_json(payload)

    def list_job_jsons(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM web_jobs ORDER BY created_unix_ms DESC, job_id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._store._row_to_job_json(row) for row in rows]

    def jobs_signature(self) -> tuple[int, int]:
        with self._store._connect() as conn:
            meta = conn.execute("SELECT jobs_rev FROM web_jobs_meta WHERE singleton = 1").fetchone()
            count_row = conn.execute("SELECT COUNT(*) FROM web_jobs").fetchone()
        rev = int(meta["jobs_rev"]) if meta is not None else 0
        count = int(count_row[0]) if count_row is not None else 0
        return count, rev

    def upsert_job(self, job: JobRecord, *, count_as_job_change: bool = True) -> None:
        job = self._materialize_applied_files(job)
        with self._store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT row_rev, last_log_seq, last_event_seq FROM web_jobs WHERE job_id = ?",
                (str(job.job_id),),
            ).fetchone()
            row_rev = (int(row["row_rev"]) if row is not None else 0) + 1
            log_count = max(
                int(getattr(job, "last_log_seq", 0) or 0),
                int(row["last_log_seq"]) if row is not None else 0,
            )
            event_count = max(
                int(getattr(job, "last_event_seq", 0) or 0),
                int(row["last_event_seq"]) if row is not None else 0,
            )
            self._store._upsert_job_row(
                conn,
                job,
                log_count=log_count,
                event_count=event_count,
                row_rev=row_rev,
            )
            self._store._touch_meta(conn, jobs_delta=1 if count_as_job_change else 0)
            conn.commit()

    def replace_job_history(
        self,
        job: JobRecord,
        *,
        log_lines: list[str],
        event_lines: list[str],
    ) -> None:
        job = self._materialize_applied_files(job, log_text="\n".join(log_lines))
        with self._store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row_rev = self._store._current_row_rev(conn, job.job_id) + 1
            self._store._upsert_job_row(
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
                items = []
                for idx, raw_line in enumerate(event_lines, start=1):
                    text = str(raw_line).rstrip("\n")
                    parsed = _read_event_frame(text)
                    items.append(
                        (
                            str(job.job_id),
                            idx,
                            text,
                            _int_or_none(parsed.get("seq")) if parsed is not None else None,
                            _none_if_blank(parsed.get("type")) if parsed is not None else None,
                            _none_if_blank(parsed.get("event")) if parsed is not None else None,
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
            self._store._touch_meta(
                conn,
                jobs_delta=1,
                logs_delta=len(log_lines),
                events_delta=len(event_lines),
            )
            conn.commit()

    def update_applied_files(self, job_id: str, files: list[str], source: str) -> None:
        with self._store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row_rev = self._store._current_row_rev(conn, str(job_id)) + 1
            conn.execute(
                """
                UPDATE web_jobs
                   SET applied_files_json = ?,
                       applied_files_source = ?,
                       row_rev = ?
                 WHERE job_id = ?
                """,
                (_json_dumps(list(files)), str(source), row_rev, str(job_id)),
            )
            self._store._touch_meta(conn, jobs_delta=1)
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
        with self._store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT last_log_seq, row_rev FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                conn.rollback()
                return 0
            seq = int(row["last_log_seq"]) + 1
            row_rev = int(row["row_rev"]) + 1
            conn.execute(
                "INSERT INTO web_job_log_lines(job_id, seq, line) VALUES (?, ?, ?)",
                (str(job_id), seq, text),
            )
            conn.execute(
                "UPDATE web_jobs SET last_log_seq = ?, row_rev = ? WHERE job_id = ?",
                (seq, row_rev, str(job_id)),
            )
            self._store._touch_meta(conn, logs_delta=1)
            conn.commit()
        return seq

    def append_event_line(self, job_id: str, raw_line: str) -> int:
        text = str(raw_line or "").rstrip("\n")
        parsed = _read_event_frame(text)
        ipc_seq = _int_or_none(parsed.get("seq")) if parsed is not None else None
        frame_type = _none_if_blank(parsed.get("type")) if parsed is not None else None
        frame_event = _none_if_blank(parsed.get("event")) if parsed is not None else None
        with self._store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT last_event_seq, row_rev FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                conn.rollback()
                return 0
            seq = int(row["last_event_seq"]) + 1
            row_rev = int(row["row_rev"]) + 1
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
            self._store._touch_meta(conn, events_delta=1)
            conn.commit()
        return seq

    def _read_raw_log_tail(self, job_id: str, *, lines: int = 200) -> str:
        limit = max(1, min(int(lines), 5000))
        with self._store._connect() as conn:
            rows = conn.execute(
                """
                SELECT line FROM web_job_log_lines
                 WHERE job_id = ?
                 ORDER BY seq DESC
                 LIMIT ?
                """,
                (str(job_id), limit),
            ).fetchall()
        return "\n".join(str(row["line"]) for row in reversed(rows))

    def read_log_tail(self, job_id: str, *, lines: int = 200) -> str:
        from .web_jobs_derived import read_effective_log_tail

        return read_effective_log_tail(self, job_id, lines=lines)

    def _read_raw_full_log(self, job_id: str) -> str:
        with self._store._connect() as conn:
            rows = conn.execute(
                "SELECT line FROM web_job_log_lines WHERE job_id = ? ORDER BY seq ASC",
                (str(job_id),),
            ).fetchall()
        return "\n".join(str(row["line"]) for row in rows)

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
        with self._store._connect() as conn:
            rows = conn.execute(
                """
                SELECT seq, raw_line, ipc_seq, frame_type, frame_event
                  FROM web_job_event_lines
                 WHERE job_id = ? AND seq > ?
                 ORDER BY seq ASC
                 LIMIT ?
                """,
                (str(job_id), int(after_seq), max(1, int(limit))),
            ).fetchall()
        return [_event_row_from_sql(row) for row in rows]

    def read_event_tail(self, job_id: str, *, lines: int = 500) -> tuple[list[EventRow], int]:
        limit = clamp_live_event_retention(lines)
        with self._store._connect() as conn:
            rows = conn.execute(
                """
                SELECT seq, raw_line, ipc_seq, frame_type, frame_event
                  FROM web_job_event_lines
                 WHERE job_id = ?
                 ORDER BY seq DESC
                 LIMIT ?
                """,
                (str(job_id), limit),
            ).fetchall()
        items = [_event_row_from_sql(row) for row in reversed(rows)]
        return items, (items[-1].seq if items else 0)

    def last_event_seq(self, job_id: str) -> int:
        with self._store._connect() as conn:
            row = conn.execute(
                "SELECT last_event_seq FROM web_jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        return int(row["last_event_seq"]) if row is not None else 0

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
        with self._store._connect() as conn:
            rows = conn.execute(
                "SELECT job_id FROM web_jobs ORDER BY created_unix_ms DESC, job_id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [str(row["job_id"]) for row in rows]

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
        with self._store._connect() as src_conn:
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
        candidates = [p for p in backup_dir.iterdir() if p.is_file() and p.name.startswith(stem)]
        candidates.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
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
        self._store._init_db()
