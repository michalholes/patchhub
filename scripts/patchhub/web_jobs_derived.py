from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .job_store import _json_dumps
from .live_event_retention import clamp_live_event_retention

if TYPE_CHECKING:
    from .models import JobRecord, WebJobsDbConfig
    from .web_jobs_db import WebJobsDatabase

__all__ = [
    "ensure_job_derived_row",
    "load_derived_payload",
    "read_effective_applied_files",
    "read_effective_full_event_text",
    "read_effective_full_log",
    "read_effective_event_tail_text",
    "read_effective_log_tail",
]


def _utc_now_parts() -> tuple[str, int]:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ"), int(now.timestamp() * 1000)


def _raw_tail_text(
    conn: sqlite3.Connection,
    *,
    table: str,
    column: str,
    job_id: str,
    lines: int,
) -> str:
    rows = conn.execute(
        f"""
        SELECT {column} FROM {table}
         WHERE job_id = ?
         ORDER BY seq DESC
         LIMIT ?
        """,
        (str(job_id), max(1, int(lines))),
    ).fetchall()
    return "\n".join(str(row[column]) for row in reversed(rows))


def _current_raw_counts(conn: sqlite3.Connection, job_id: str) -> tuple[int, int]:
    log_row = conn.execute(
        "SELECT COUNT(*) AS n FROM web_job_log_lines WHERE job_id = ?",
        (str(job_id),),
    ).fetchone()
    event_row = conn.execute(
        "SELECT COUNT(*) AS n FROM web_job_event_lines WHERE job_id = ?",
        (str(job_id),),
    ).fetchone()
    return (
        int(log_row["n"]) if log_row is not None else 0,
        int(event_row["n"]) if event_row is not None else 0,
    )


def _preserved_tail(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    table: str,
    column: str,
    current_text: str | None,
    fallback_lines: int,
) -> str:
    if current_text:
        return str(current_text)
    return _raw_tail_text(
        conn,
        table=table,
        column=column,
        job_id=str(job_id),
        lines=max(1, int(fallback_lines)),
    )


def ensure_job_derived_row(
    conn: sqlite3.Connection,
    *,
    cfg: WebJobsDbConfig,
    job: JobRecord,
    log_count: int,
    event_count: int,
    keep_tail_lines: int = 200,
) -> None:
    raw_log_count, raw_event_count = _current_raw_counts(conn, job.job_id)
    existing = conn.execute(
        "SELECT * FROM web_job_derived WHERE job_id = ?",
        (str(job.job_id),),
    ).fetchone()
    existing_rev = int(existing["derived_rev"]) if existing is not None else 0
    now_utc, now_unix_ms = _utc_now_parts()
    created_utc = str(existing["created_utc"]) if existing is not None else now_utc
    created_unix_ms = int(existing["created_unix_ms"]) if existing is not None else now_unix_ms
    updated_utc, updated_unix_ms = now_utc, now_unix_ms

    compact_log_tail_text = _preserved_tail(
        conn,
        job_id=job.job_id,
        table="web_job_log_lines",
        column="line",
        current_text=(existing["compact_log_tail_text"] if existing is not None else None),
        fallback_lines=keep_tail_lines,
    )
    compact_event_tail_text = _preserved_tail(
        conn,
        job_id=job.job_id,
        table="web_job_event_lines",
        column="raw_line",
        current_text=(existing["compact_event_tail_text"] if existing is not None else None),
        fallback_lines=keep_tail_lines,
    )

    source_row_rev = int(getattr(job, "row_rev", 0) or 0)
    if source_row_rev <= 0:
        source_row_rev = int(
            conn.execute(
                "SELECT row_rev FROM web_jobs WHERE job_id = ?",
                (str(job.job_id),),
            ).fetchone()["row_rev"]
        )

    payload = (
        str(job.job_id),
        _json_dumps(list(job.applied_files)),
        str(job.applied_files_source or "unavailable"),
        compact_log_tail_text,
        compact_event_tail_text,
        existing_rev + 1,
        created_utc,
        created_unix_ms,
        updated_utc,
        updated_unix_ms,
        source_row_rev,
        raw_log_count,
        raw_event_count,
        str(getattr(job, "status", "") or ""),
        str(getattr(job, "ended_utc", "") or ""),
    )
    conn.execute(
        """
        INSERT INTO web_job_derived(
            job_id,
            applied_files_json,
            applied_files_source,
            compact_log_tail_text,
            compact_event_tail_text,
            derived_rev,
            created_utc,
            created_unix_ms,
            updated_utc,
            updated_unix_ms,
            source_row_rev,
            raw_log_lines_compacted,
            raw_event_lines_compacted,
            terminal_status,
            terminal_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            applied_files_json = excluded.applied_files_json,
            applied_files_source = excluded.applied_files_source,
            compact_log_tail_text = excluded.compact_log_tail_text,
            compact_event_tail_text = excluded.compact_event_tail_text,
            derived_rev = excluded.derived_rev,
            updated_utc = excluded.updated_utc,
            updated_unix_ms = excluded.updated_unix_ms,
            source_row_rev = excluded.source_row_rev,
            raw_log_lines_compacted = excluded.raw_log_lines_compacted,
            raw_event_lines_compacted = excluded.raw_event_lines_compacted,
            terminal_status = excluded.terminal_status,
            terminal_utc = excluded.terminal_utc
        """,
        payload,
    )


def load_derived_payload(
    source: WebJobsDatabase | sqlite3.Connection,
    job_id: str,
) -> dict[str, Any] | None:
    if isinstance(source, sqlite3.Connection):
        row = source.execute(
            "SELECT * FROM web_job_derived WHERE job_id = ?",
            (str(job_id),),
        ).fetchone()
    elif hasattr(source, "_store") and hasattr(source._store, "_connect"):
        with source._store._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                "SELECT * FROM web_job_derived WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
    else:
        return None
    if row is None:
        return None
    return {
        "job_id": str(row["job_id"]),
        "applied_files": json.loads(str(row["applied_files_json"])),
        "applied_files_source": str(row["applied_files_source"]),
        "compact_log_tail_text": str(row["compact_log_tail_text"] or ""),
        "compact_event_tail_text": str(row["compact_event_tail_text"] or ""),
        "derived_rev": int(row["derived_rev"]),
        "source_row_rev": int(row["source_row_rev"]),
        "updated_utc": str(row["updated_utc"]),
        "updated_unix_ms": int(row["updated_unix_ms"]),
        "raw_log_lines_compacted": int(row["raw_log_lines_compacted"]),
        "raw_event_lines_compacted": int(row["raw_event_lines_compacted"]),
        "terminal_status": str(row["terminal_status"]),
        "terminal_utc": str(row["terminal_utc"] or ""),
    }


def _tail_slice(text: str, *, lines: int) -> str:
    if not text:
        return ""
    parts = str(text).splitlines()
    return "\n".join(parts[-max(1, int(lines)) :])


def _derived_text(job_db: WebJobsDatabase, job_id: str, field: str) -> str:
    derived = load_derived_payload(job_db, job_id)
    if derived is None:
        return ""
    return str(derived.get(field) or "")


def read_effective_full_log(job_db: WebJobsDatabase, job_id: str) -> str:
    raw_text = job_db._read_raw_full_log(job_id)
    if raw_text:
        return raw_text
    return _derived_text(job_db, job_id, "compact_log_tail_text")


def read_effective_full_event_text(job_db: WebJobsDatabase, job_id: str) -> str:
    rows = job_db.read_event_rows(job_id, after_seq=0, limit=1_000_000)
    if rows:
        return "\n".join(row.raw_line for row in rows)
    return _derived_text(job_db, job_id, "compact_event_tail_text")


def read_effective_event_tail_text(
    job_db: WebJobsDatabase,
    job_id: str,
    *,
    lines: int = 500,
) -> str:
    limit = clamp_live_event_retention(lines)
    rows, _last_seq = job_db.read_event_tail(job_id, lines=limit)
    if rows:
        return "\n".join(row.raw_line for row in rows)
    return _tail_slice(
        _derived_text(job_db, job_id, "compact_event_tail_text"),
        lines=limit,
    )


def read_effective_applied_files(job_db: WebJobsDatabase, job_id: str) -> tuple[list[str], str]:
    derived = load_derived_payload(job_db, job_id)
    if derived is not None:
        return (
            [str(item) for item in list(derived.get("applied_files") or [])],
            str(derived.get("applied_files_source", "unavailable")),
        )
    raw = job_db.load_job_json(job_id)
    if raw is None:
        return [], "unavailable"
    return (
        [str(item) for item in list(raw.get("applied_files") or [])],
        str(raw.get("applied_files_source", "unavailable")),
    )


def read_effective_log_tail(job_db: WebJobsDatabase, job_id: str, *, lines: int = 200) -> str:
    limit = clamp_live_event_retention(lines)
    raw_tail = job_db._read_raw_log_tail(job_id, lines=limit)
    if raw_tail:
        return raw_tail
    return _tail_slice(_derived_text(job_db, job_id, "compact_log_tail_text"), lines=limit)
