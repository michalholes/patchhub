from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, TypeAlias, cast, runtime_checkable

from .job_store import json_dumps
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


SqlParams: TypeAlias = tuple[object, ...]


@runtime_checkable
class _RowLike(Protocol):
    def keys(self) -> object: ...

    def __getitem__(self, key: object, /) -> object: ...


@runtime_checkable
class _ConnectSource(Protocol):
    def connect(self) -> sqlite3.Connection: ...


@runtime_checkable
class _JobJsonSource(Protocol):
    def load_job_json(self, job_id: str) -> dict[str, object] | None: ...


def _obj_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw_dict = cast(dict[object, object], value)
    out: dict[str, object] = {}
    for key, item in raw_dict.items():
        if isinstance(key, str):
            out[key] = item
    return out


def _obj_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(cast(list[object], value))
    return []


def _row_dict(value: object) -> dict[str, object]:
    row = _obj_dict(value)
    if row is not None:
        return row
    if not isinstance(value, _RowLike):
        return {}
    out: dict[str, object] = {}
    keys = _obj_list(value.keys())
    for key_raw in keys:
        key = str(key_raw)
        out[key] = value[key]
    return out


def _query_one_dict(
    conn: sqlite3.Connection,
    sql: str,
    params: SqlParams = (),
) -> dict[str, object]:
    row_obj = cast(object, conn.execute(sql, params).fetchone())
    return _row_dict(row_obj)


def _query_all_dicts(
    conn: sqlite3.Connection,
    sql: str,
    params: SqlParams = (),
) -> list[dict[str, object]]:
    rows_obj = cast(object, conn.execute(sql, params).fetchall())
    rows_raw = _obj_list(rows_obj)
    return [_row_dict(item) for item in rows_raw]


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value if value is not None else default))
    except Exception:
        return default


def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _json_loads_obj(text: str) -> object:
    parsed: object = json.loads(text)
    return parsed


def _str_list(value: object) -> list[str]:
    return [str(item) for item in _obj_list(value)]


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
    rows = _query_all_dicts(
        conn,
        f"""
        SELECT {column} FROM {table}
         WHERE job_id = ?
         ORDER BY seq DESC
         LIMIT ?
        """,
        (str(job_id), max(1, int(lines))),
    )
    return "\n".join(str(row.get(column, "")) for row in reversed(rows))


def _current_raw_counts(conn: sqlite3.Connection, job_id: str) -> tuple[int, int]:
    log_row = _query_one_dict(
        conn,
        "SELECT COUNT(*) AS n FROM web_job_log_lines WHERE job_id = ?",
        (str(job_id),),
    )
    event_row = _query_one_dict(
        conn,
        "SELECT COUNT(*) AS n FROM web_job_event_lines WHERE job_id = ?",
        (str(job_id),),
    )
    return (_as_int(log_row.get("n"), 0), _as_int(event_row.get("n"), 0))


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
    del cfg, log_count, event_count
    raw_log_count, raw_event_count = _current_raw_counts(conn, job.job_id)
    existing = _query_one_dict(
        conn,
        "SELECT * FROM web_job_derived WHERE job_id = ?",
        (str(job.job_id),),
    )
    has_existing = bool(existing)
    existing_rev = _as_int(existing.get("derived_rev"), 0)
    now_utc, now_unix_ms = _utc_now_parts()
    created_utc = str(existing.get("created_utc")) if has_existing else now_utc
    created_unix_ms = _as_int(existing.get("created_unix_ms"), now_unix_ms)
    updated_utc, updated_unix_ms = now_utc, now_unix_ms

    compact_log_tail_text = _preserved_tail(
        conn,
        job_id=job.job_id,
        table="web_job_log_lines",
        column="line",
        current_text=_as_optional_str(existing.get("compact_log_tail_text")),
        fallback_lines=keep_tail_lines,
    )
    compact_event_tail_text = _preserved_tail(
        conn,
        job_id=job.job_id,
        table="web_job_event_lines",
        column="raw_line",
        current_text=_as_optional_str(existing.get("compact_event_tail_text")),
        fallback_lines=keep_tail_lines,
    )

    source_row_rev = _as_int(job.row_rev, 0)
    if source_row_rev <= 0:
        source_row = _query_one_dict(
            conn,
            "SELECT row_rev FROM web_jobs WHERE job_id = ?",
            (str(job.job_id),),
        )
        source_row_rev = _as_int(source_row.get("row_rev"), 0)

    payload = (
        str(job.job_id),
        json_dumps(list(job.applied_files)),
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
        str(job.status or ""),
        str(job.ended_utc or ""),
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
    source: _ConnectSource | sqlite3.Connection,
    job_id: str,
) -> dict[str, object] | None:
    row: dict[str, object]
    if isinstance(source, sqlite3.Connection):
        row = _query_one_dict(
            source,
            "SELECT * FROM web_job_derived WHERE job_id = ?",
            (str(job_id),),
        )
    else:
        with source.connect() as conn:
            row = _query_one_dict(
                conn,
                "SELECT * FROM web_job_derived WHERE job_id = ?",
                (str(job_id),),
            )
    if not row:
        return None
    applied_raw = _json_loads_obj(str(row.get("applied_files_json", "[]")))
    return {
        "job_id": str(row.get("job_id", "")),
        "applied_files": _str_list(applied_raw),
        "applied_files_source": str(row.get("applied_files_source", "unavailable")),
        "compact_log_tail_text": str(row.get("compact_log_tail_text") or ""),
        "compact_event_tail_text": str(row.get("compact_event_tail_text") or ""),
        "derived_rev": _as_int(row.get("derived_rev"), 0),
        "source_row_rev": _as_int(row.get("source_row_rev"), 0),
        "updated_utc": str(row.get("updated_utc", "")),
        "updated_unix_ms": _as_int(row.get("updated_unix_ms"), 0),
        "raw_log_lines_compacted": _as_int(row.get("raw_log_lines_compacted"), 0),
        "raw_event_lines_compacted": _as_int(row.get("raw_event_lines_compacted"), 0),
        "terminal_status": str(row.get("terminal_status", "")),
        "terminal_utc": str(row.get("terminal_utc") or ""),
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
    raw_text = job_db.read_raw_full_log(job_id)
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


def read_effective_applied_files(job_db: _JobJsonSource, job_id: str) -> tuple[list[str], str]:
    source_obj = cast(object, job_db)
    derived = (
        load_derived_payload(source_obj, job_id) if isinstance(source_obj, _ConnectSource) else None
    )
    if derived is not None:
        return (
            _str_list(derived.get("applied_files")),
            str(derived.get("applied_files_source", "unavailable")),
        )
    raw = job_db.load_job_json(job_id)
    if raw is None:
        return [], "unavailable"
    return (
        _str_list(raw.get("applied_files")),
        str(raw.get("applied_files_source", "unavailable")),
    )


def read_effective_log_tail(job_db: WebJobsDatabase, job_id: str, *, lines: int = 200) -> str:
    limit = clamp_live_event_retention(lines)
    raw_tail = job_db.read_raw_log_tail(job_id, lines=limit)
    if raw_tail:
        return raw_tail
    return _tail_slice(_derived_text(job_db, job_id, "compact_log_tail_text"), lines=limit)
