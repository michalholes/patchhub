from __future__ import annotations

import sqlite3
import tomllib
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import JobRecord, WebJobsDbConfig

_TERMINAL_STATUSES = {"success", "fail", "canceled"}


@dataclass(frozen=True)
class RetentionSettings:
    max_completed_log_lines: int
    max_completed_event_lines: int
    max_completed_age_days: int
    keep_recent_terminal_per_mode: int
    compact_tail_lines: int
    reclaim_trigger_policy: str
    reclaim_interval_seconds: int
    reclaim_min_pruned_rows: int


def load_retention_settings(cfg: WebJobsDbConfig) -> RetentionSettings:
    cfg_path = cfg.db_path.parents[2] / "scripts" / "patchhub" / "patchhub.toml"
    raw: dict[str, object] = {}
    if cfg_path.is_file():
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    block = raw.get("web_jobs_retention", {})
    if not isinstance(block, dict):
        block = {}
    return RetentionSettings(
        max_completed_log_lines=max(
            1,
            int(
                block.get(
                    "max_completed_job_raw_log_lines",
                    cfg.retention_thresholds.get("compact_after_log_lines", 100000),
                )
            ),
        ),
        max_completed_event_lines=max(
            1,
            int(
                block.get(
                    "max_completed_job_raw_event_lines",
                    cfg.retention_thresholds.get("compact_after_event_lines", 100000),
                )
            ),
        ),
        max_completed_age_days=max(
            0,
            int(
                block.get(
                    "max_completed_job_raw_age_days",
                    cfg.retention_defaults.get("logs_keep_days", 30),
                )
            ),
        ),
        keep_recent_terminal_per_mode=max(
            0,
            int(
                block.get(
                    "keep_recent_terminal_jobs_per_mode",
                    cfg.retention_thresholds.get("compact_after_jobs", 0),
                )
            ),
        ),
        compact_tail_lines=max(1, int(block.get("compact_tail_lines", 200))),
        reclaim_trigger_policy=str(
            block.get("reclaim_trigger_policy", "after_compaction") or "manual"
        ),
        reclaim_interval_seconds=max(0, int(block.get("reclaim_interval_seconds", 0))),
        reclaim_min_pruned_rows=max(1, int(block.get("reclaim_min_pruned_rows", 1))),
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
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE job_id = ?",
        (str(job_id),),
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def _tail_text(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    table: str,
    column: str,
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


def _age_eligible(row: sqlite3.Row, settings: RetentionSettings, now_ms: int) -> bool:
    if settings.max_completed_age_days <= 0:
        return False
    terminal_ms = _utc_ms(str(row["ended_utc"] or row["created_utc"] or ""))
    if terminal_ms <= 0:
        return False
    max_age_ms = settings.max_completed_age_days * 24 * 60 * 60 * 1000
    return now_ms - terminal_ms >= max_age_ms


def _upsert_compact_derived(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    settings: RetentionSettings,
    raw_log_count: int,
    raw_event_count: int,
) -> None:
    derived = conn.execute(
        (
            "SELECT applied_files_json, applied_files_source, derived_rev, "
            "created_utc, created_unix_ms FROM web_job_derived WHERE job_id = ?"
        ),
        (str(row["job_id"]),),
    ).fetchone()
    updated_utc, updated_unix_ms = _now_parts()
    created_utc = str(derived["created_utc"]) if derived is not None else updated_utc
    created_unix_ms = int(derived["created_unix_ms"]) if derived is not None else updated_unix_ms
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
                derived["applied_files_json"] if derived is not None else row["applied_files_json"]
            ),
            str(
                derived["applied_files_source"]
                if derived is not None
                else row["applied_files_source"]
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
            (int(derived["derived_rev"]) if derived is not None else 0) + 1,
            created_utc,
            created_unix_ms,
            updated_utc,
            updated_unix_ms,
            int(row["row_rev"]),
            raw_log_count,
            raw_event_count,
            str(row["status"]),
            str(row["ended_utc"] or row["created_utc"] or ""),
        ),
    )


def _maybe_reclaim(conn: sqlite3.Connection, settings: RetentionSettings, pruned_rows: int) -> bool:
    if pruned_rows < settings.reclaim_min_pruned_rows:
        return False
    if settings.reclaim_trigger_policy not in {
        "after_compaction",
        "interval",
        "after_compaction_or_interval",
    }:
        return False
    row = conn.execute(
        "SELECT last_reclaim_unix_ms FROM web_jobs_housekeeping WHERE singleton = 1"
    ).fetchone()
    last_reclaim_ms = int(row["last_reclaim_unix_ms"]) if row is not None else 0
    interval_ms = max(0, settings.reclaim_interval_seconds) * 1000
    now_ms = _now_parts()[1]
    if interval_ms > 0 and now_ms - last_reclaim_ms < interval_ms:
        return False
    with suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    conn.execute(f"PRAGMA incremental_vacuum({max(1, pruned_rows)})")
    return True


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
    rows = conn.execute(
        """
        SELECT * FROM web_jobs
         WHERE status IN ('success', 'fail', 'canceled')
         ORDER BY created_unix_ms DESC, job_id DESC
        """
    ).fetchall()
    if not rows:
        return

    now_ms = _now_parts()[1]
    recent_by_mode: dict[str, int] = {}
    compacted_jobs = pruned_log_rows = pruned_event_rows = 0
    for row in rows:
        mode = str(row["mode"])
        seen = recent_by_mode.get(mode, 0)
        if seen < settings.keep_recent_terminal_per_mode:
            recent_by_mode[mode] = seen + 1
            continue
        job_id = str(row["job_id"])
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

    if compacted_jobs <= 0:
        return
    updated_ms = _now_parts()[1]
    conn.execute(
        """
        UPDATE web_jobs_meta
           SET jobs_rev = jobs_rev + ?,
               logs_rev = logs_rev - ?,
               events_rev = events_rev - ?,
               updated_unix_ms = ?
         WHERE singleton = 1
        """,
        (compacted_jobs, pruned_log_rows, pruned_event_rows, updated_ms),
    )
    reclaimed = _maybe_reclaim(conn, settings, pruned_log_rows + pruned_event_rows)
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
            compacted_jobs,
            pruned_log_rows,
            pruned_event_rows,
            updated_ms,
            1 if reclaimed else 0,
        ),
    )
