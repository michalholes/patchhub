from __future__ import annotations

import sqlite3
import tomllib
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, TypeAlias, cast, runtime_checkable

if TYPE_CHECKING:
    from .models import JobRecord, WebJobsDbConfig

_TERMINAL_STATUSES = {"success", "fail", "canceled"}


@dataclass(frozen=True)
class RetentionSettings:
    jobs_keep_days: int
    max_completed_log_lines: int
    max_completed_event_lines: int
    max_completed_age_days: int
    keep_recent_terminal_per_mode: int
    compact_tail_lines: int
    reclaim_trigger_policy: str
    reclaim_interval_seconds: int
    reclaim_min_pruned_rows: int


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


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value if value is not None else default))
    except Exception:
        return default


SqlParams: TypeAlias = tuple[object, ...]


@runtime_checkable
class _RowLike(Protocol):
    def keys(self) -> object: ...

    def __getitem__(self, key: object) -> object: ...


def _row_dict(value: object) -> dict[str, object]:
    row = _obj_dict(value)
    if row is not None:
        return row
    if not isinstance(value, _RowLike):
        return {}
    out: dict[str, object] = {}
    with suppress(Exception):
        keys_obj = value.keys()
        keys_raw = _obj_list(keys_obj)
        for key_raw in keys_raw:
            key = str(key_raw)
            out[key] = value[key]
    return out


def _row_dicts(value: object) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in _obj_list(value):
        out.append(_row_dict(row))
    return out


def _as_str(value: object, default: str = "") -> str:
    text = str(value if value is not None else default)
    return text


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
    return _row_dicts(rows_obj)


def load_retention_settings(cfg: WebJobsDbConfig) -> RetentionSettings:
    cfg_path = cfg.db_path.parents[2] / "scripts" / "patchhub" / "patchhub.toml"
    raw: dict[str, object] = {}
    if cfg_path.is_file():
        parsed: object = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        loaded = _obj_dict(parsed)
        raw = loaded if loaded is not None else {}
    block_obj = raw.get("web_jobs_retention", {})
    block = _obj_dict(block_obj)
    if block is None:
        block = {}
    return RetentionSettings(
        jobs_keep_days=max(
            0,
            _as_int(
                block.get("jobs_keep_days", cfg.retention_defaults.get("jobs_keep_days", 30)),
                cfg.retention_defaults.get("jobs_keep_days", 30),
            ),
        ),
        max_completed_log_lines=max(
            1,
            _as_int(
                block.get(
                    "max_completed_job_raw_log_lines",
                    cfg.retention_thresholds.get("compact_after_log_lines", 100000),
                ),
                cfg.retention_thresholds.get("compact_after_log_lines", 100000),
            ),
        ),
        max_completed_event_lines=max(
            1,
            _as_int(
                block.get(
                    "max_completed_job_raw_event_lines",
                    cfg.retention_thresholds.get("compact_after_event_lines", 100000),
                ),
                cfg.retention_thresholds.get("compact_after_event_lines", 100000),
            ),
        ),
        max_completed_age_days=max(
            0,
            _as_int(
                block.get(
                    "max_completed_job_raw_age_days",
                    cfg.retention_defaults.get("logs_keep_days", 30),
                ),
                cfg.retention_defaults.get("logs_keep_days", 30),
            ),
        ),
        keep_recent_terminal_per_mode=max(
            0,
            _as_int(
                block.get(
                    "keep_recent_terminal_jobs_per_mode",
                    cfg.retention_thresholds.get("compact_after_jobs", 0),
                ),
                cfg.retention_thresholds.get("compact_after_jobs", 0),
            ),
        ),
        compact_tail_lines=max(1, _as_int(block.get("compact_tail_lines", 200), 200)),
        reclaim_trigger_policy=str(
            block.get("reclaim_trigger_policy", "after_compaction") or "manual"
        ),
        reclaim_interval_seconds=max(0, _as_int(block.get("reclaim_interval_seconds", 0), 0)),
        reclaim_min_pruned_rows=max(1, _as_int(block.get("reclaim_min_pruned_rows", 1), 1)),
    )


def _utc_ms(value: str | None) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return 0
    return int(dt.replace(tzinfo=UTC).timestamp() * 1000)


def _now_parts() -> tuple[str, int]:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ"), int(now.timestamp() * 1000)


def _count_rows(conn: sqlite3.Connection, table: str, job_id: str) -> int:
    row = _query_one_dict(
        conn,
        f"SELECT COUNT(*) AS n FROM {table} WHERE job_id = ?",
        (str(job_id),),
    )
    return _as_int(row.get("n"), 0)


def _tail_text(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    table: str,
    column: str,
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
    out: list[str] = []
    for row in reversed(rows):
        out.append(_as_str(row.get(column), ""))
    return "\n".join(out)


def _age_eligible(row: dict[str, object], settings: RetentionSettings, now_ms: int) -> bool:
    if settings.max_completed_age_days <= 0:
        return False
    terminal_ms = _utc_ms(_as_str(row.get("ended_utc") or row.get("created_utc"), ""))
    if terminal_ms <= 0:
        return False
    max_age_ms = settings.max_completed_age_days * 24 * 60 * 60 * 1000
    return now_ms - terminal_ms >= max_age_ms


def _prune_eligible(row: dict[str, object], settings: RetentionSettings, now_ms: int) -> bool:
    if settings.jobs_keep_days <= 0:
        return False
    terminal_ms = _utc_ms(_as_str(row.get("ended_utc") or row.get("created_utc"), ""))
    if terminal_ms <= 0:
        return False
    max_age_ms = settings.jobs_keep_days * 24 * 60 * 60 * 1000
    return now_ms - terminal_ms >= max_age_ms


def _upsert_compact_derived(
    conn: sqlite3.Connection,
    *,
    row: dict[str, object],
    settings: RetentionSettings,
    raw_log_count: int,
    raw_event_count: int,
) -> None:
    derived = _query_one_dict(
        conn,
        (
            "SELECT applied_files_json, applied_files_source, derived_rev, "
            "created_utc, created_unix_ms FROM web_job_derived WHERE job_id = ?"
        ),
        (str(row["job_id"]),),
    )
    updated_utc, updated_unix_ms = _now_parts()
    has_derived = bool(derived)
    created_utc = _as_str(derived.get("created_utc"), updated_utc) if has_derived else updated_utc
    created_unix_ms = _as_int(derived.get("created_unix_ms"), updated_unix_ms)
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
        (
            str(row["job_id"]),
            str(
                derived.get("applied_files_json")
                if has_derived
                else row.get("applied_files_json", "")
            ),
            str(
                derived.get("applied_files_source")
                if has_derived
                else row.get("applied_files_source", "")
            ),
            _tail_text(
                conn,
                job_id=str(row["job_id"]),
                table="web_job_log_lines",
                column="line",
                lines=settings.compact_tail_lines,
            ),
            _tail_text(
                conn,
                job_id=str(row["job_id"]),
                table="web_job_event_lines",
                column="raw_line",
                lines=settings.compact_tail_lines,
            ),
            (_as_int(derived.get("derived_rev"), 0) if has_derived else 0) + 1,
            created_utc,
            created_unix_ms,
            updated_utc,
            updated_unix_ms,
            _as_int(row.get("row_rev"), 0),
            raw_log_count,
            raw_event_count,
            _as_str(row.get("status"), ""),
            _as_str(row.get("ended_utc") or row.get("created_utc"), ""),
        ),
    )


def _prune_terminal_job_row(
    conn: sqlite3.Connection,
    *,
    job_id: str,
) -> tuple[int, int]:
    raw_log_count = _count_rows(conn, "web_job_log_lines", job_id)
    raw_event_count = _count_rows(conn, "web_job_event_lines", job_id)
    conn.execute("DELETE FROM web_job_log_lines WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM web_job_event_lines WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM web_job_derived WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM web_job_rollback_authority WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM web_jobs WHERE job_id = ?", (job_id,))
    return raw_log_count, raw_event_count


def _maybe_reclaim(conn: sqlite3.Connection, settings: RetentionSettings, pruned_rows: int) -> bool:
    if pruned_rows < settings.reclaim_min_pruned_rows:
        return False
    if settings.reclaim_trigger_policy not in {
        "after_compaction",
        "interval",
        "after_compaction_or_interval",
    }:
        return False
    row = _query_one_dict(
        conn,
        "SELECT last_reclaim_unix_ms FROM web_jobs_housekeeping WHERE singleton = 1",
    )
    last_reclaim_ms = _as_int(row.get("last_reclaim_unix_ms"), 0)
    interval_ms = max(0, settings.reclaim_interval_seconds) * 1000
    now_ms = _now_parts()[1]
    if interval_ms > 0 and now_ms - last_reclaim_ms < interval_ms:
        return False
    with suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    conn.execute(f"PRAGMA incremental_vacuum({max(1, pruned_rows)})")
    return True


def _run_retention_pass(
    conn: sqlite3.Connection,
    *,
    settings: RetentionSettings,
) -> bool:
    rows = _query_all_dicts(
        conn,
        """
        SELECT * FROM web_jobs
         WHERE status IN ('success', 'fail', 'canceled')
         ORDER BY created_unix_ms DESC, job_id DESC
        """,
    )
    if not rows:
        return False

    now_ms = _now_parts()[1]
    recent_by_mode: dict[str, int] = {}
    compacted_jobs = pruned_jobs = pruned_log_rows = pruned_event_rows = 0
    for row in rows:
        mode = _as_str(row.get("mode"), "")
        seen = recent_by_mode.get(mode, 0)
        if seen < settings.keep_recent_terminal_per_mode:
            recent_by_mode[mode] = seen + 1
            continue
        job_id = _as_str(row.get("job_id"), "")
        if _prune_eligible(row, settings, now_ms):
            raw_log_count, raw_event_count = _prune_terminal_job_row(conn, job_id=job_id)
            pruned_jobs += 1
            pruned_log_rows += raw_log_count
            pruned_event_rows += raw_event_count
            continue
        raw_log_count = _count_rows(conn, "web_job_log_lines", job_id)
        raw_event_count = _count_rows(conn, "web_job_event_lines", job_id)
        if raw_log_count <= 0 and raw_event_count <= 0:
            continue
        if not (
            raw_log_count > settings.max_completed_log_lines
            or raw_event_count > settings.max_completed_event_lines
            or _age_eligible(row, settings, now_ms)
        ):
            continue
        _upsert_compact_derived(
            conn,
            row=row,
            settings=settings,
            raw_log_count=raw_log_count,
            raw_event_count=raw_event_count,
        )
        conn.execute("DELETE FROM web_job_log_lines WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM web_job_event_lines WHERE job_id = ?", (job_id,))
        conn.execute("UPDATE web_jobs SET row_rev = row_rev + 1 WHERE job_id = ?", (job_id,))
        compacted_jobs += 1
        pruned_log_rows += raw_log_count
        pruned_event_rows += raw_event_count

    if compacted_jobs <= 0 and pruned_jobs <= 0:
        return False
    updated_ms = _now_parts()[1]
    changed_jobs = compacted_jobs + pruned_jobs
    conn.execute(
        """
        UPDATE web_jobs_meta
           SET jobs_rev = jobs_rev + ?,
                logs_rev = logs_rev - ?,
                events_rev = events_rev - ?,
                updated_unix_ms = ?
         WHERE singleton = 1
        """,
        (changed_jobs, pruned_log_rows, pruned_event_rows, updated_ms),
    )
    reclaimed = _maybe_reclaim(
        conn,
        settings,
        pruned_log_rows + pruned_event_rows + changed_jobs,
    )
    conn.execute(
        """
        INSERT INTO web_jobs_housekeeping(
            singleton,
            last_reclaim_unix_ms,
            prune_ops,
            pruned_log_rows,
            pruned_event_rows,
            updated_unix_ms
        ) VALUES(1, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET
            last_reclaim_unix_ms = CASE
                WHEN ? THEN excluded.last_reclaim_unix_ms
                ELSE web_jobs_housekeeping.last_reclaim_unix_ms
            END,
            prune_ops = web_jobs_housekeeping.prune_ops + excluded.prune_ops,
            pruned_log_rows = (
                web_jobs_housekeeping.pruned_log_rows + excluded.pruned_log_rows
            ),
            pruned_event_rows = (
                web_jobs_housekeeping.pruned_event_rows + excluded.pruned_event_rows
            ),
            updated_unix_ms = excluded.updated_unix_ms
        """,
        (
            updated_ms,
            changed_jobs,
            pruned_log_rows,
            pruned_event_rows,
            updated_ms,
            1 if reclaimed else 0,
        ),
    )
    return True


def run_retention_janitor(
    conn: sqlite3.Connection,
    *,
    cfg: WebJobsDbConfig,
) -> bool:
    settings = load_retention_settings(cfg)
    return _run_retention_pass(conn, settings=settings)


def maybe_compact_terminal_job(
    conn: sqlite3.Connection,
    *,
    cfg: WebJobsDbConfig,
    job: JobRecord,
    expected_log_count: int,
    expected_event_count: int,
) -> None:
    del expected_log_count, expected_event_count
    if str(job.status) not in _TERMINAL_STATUSES:
        return
    settings = load_retention_settings(cfg)
    _run_retention_pass(conn, settings=settings)
