from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import cast

_WEB_JOBS_STATS_OUTCOMES = {"success", "fail", "canceled", "unknown"}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def _utc_now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _web_jobs_stats_totals(conn: sqlite3.Connection) -> tuple[int, int, int, int, int]:
    row_obj = cast(
        object,
        conn.execute(
            """
        SELECT
            COUNT(*) AS jobs_total,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_total,
            SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) AS fail_total,
            SUM(CASE WHEN status = 'canceled' THEN 1 ELSE 0 END) AS canceled_total,
            SUM(CASE WHEN status = 'unknown' THEN 1 ELSE 0 END) AS unknown_total
          FROM web_jobs
        """,
        ).fetchone(),
    )
    row = cast(tuple[object, object, object, object, object] | None, row_obj)
    if row is None:
        return (0, 0, 0, 0, 0)
    return (
        _as_int(row[0], 0),
        _as_int(row[1], 0),
        _as_int(row[2], 0),
        _as_int(row[3], 0),
        _as_int(row[4], 0),
    )


def ensure_web_jobs_stats(conn: sqlite3.Connection) -> None:
    row_obj = cast(
        object,
        conn.execute(
            "SELECT 1 FROM web_jobs_stats WHERE singleton = 1",
        ).fetchone(),
    )
    row = cast(tuple[object, ...] | None, row_obj)
    if row is not None:
        return
    jobs_total, success_total, fail_total, canceled_total, unknown_total = _web_jobs_stats_totals(
        conn
    )
    conn.execute(
        """
        INSERT INTO web_jobs_stats(
            singleton,
            jobs_total,
            success_total,
            fail_total,
            canceled_total,
            unknown_total,
            updated_unix_ms
        ) VALUES(1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO NOTHING
        """,
        (
            jobs_total,
            success_total,
            fail_total,
            canceled_total,
            unknown_total,
            _utc_now_ms(),
        ),
    )


def apply_web_jobs_stats_delta(
    conn: sqlite3.Connection,
    *,
    jobs_total_delta: int = 0,
    success_total_delta: int = 0,
    fail_total_delta: int = 0,
    canceled_total_delta: int = 0,
    unknown_total_delta: int = 0,
) -> None:
    if not any(
        (
            jobs_total_delta,
            success_total_delta,
            fail_total_delta,
            canceled_total_delta,
            unknown_total_delta,
        )
    ):
        return
    conn.execute(
        """
        INSERT INTO web_jobs_stats(
            singleton,
            jobs_total,
            success_total,
            fail_total,
            canceled_total,
            unknown_total,
            updated_unix_ms
        ) VALUES(1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET
            jobs_total = web_jobs_stats.jobs_total + excluded.jobs_total,
            success_total = web_jobs_stats.success_total + excluded.success_total,
            fail_total = web_jobs_stats.fail_total + excluded.fail_total,
            canceled_total = web_jobs_stats.canceled_total + excluded.canceled_total,
            unknown_total = web_jobs_stats.unknown_total + excluded.unknown_total,
            updated_unix_ms = excluded.updated_unix_ms
        """,
        (
            int(jobs_total_delta),
            int(success_total_delta),
            int(fail_total_delta),
            int(canceled_total_delta),
            int(unknown_total_delta),
            _utc_now_ms(),
        ),
    )


def _stat_outcome_delta(status: object) -> tuple[int, int, int, int]:
    outcome = str(status or "").strip()
    if outcome == "success":
        return (1, 0, 0, 0)
    if outcome == "fail":
        return (0, 1, 0, 0)
    if outcome == "canceled":
        return (0, 0, 1, 0)
    if outcome == "unknown":
        return (0, 0, 0, 1)
    return (0, 0, 0, 0)


def job_stats_delta(existing_status: object, new_status: object) -> tuple[int, int, int, int, int]:
    jobs_total_delta = 0 if str(existing_status or "") else 1
    old_outcome = str(existing_status or "").strip()
    new_outcome = str(new_status or "").strip()
    if old_outcome in _WEB_JOBS_STATS_OUTCOMES:
        return (jobs_total_delta, 0, 0, 0, 0)
    if new_outcome not in _WEB_JOBS_STATS_OUTCOMES:
        return (jobs_total_delta, 0, 0, 0, 0)
    success_delta, fail_delta, canceled_delta, unknown_delta = _stat_outcome_delta(new_outcome)
    return (
        jobs_total_delta,
        success_delta,
        fail_delta,
        canceled_delta,
        unknown_delta,
    )


def summarize_job_rows(rows: list[dict[str, object]]) -> dict[str, int]:
    jobs_total = len(rows)
    success_total = 0
    fail_total = 0
    canceled_total = 0
    unknown_total = 0
    for row in rows:
        status = str(row.get("status", "") or "").strip()
        if status == "success":
            success_total += 1
        elif status == "fail":
            fail_total += 1
        elif status == "canceled":
            canceled_total += 1
        elif status == "unknown":
            unknown_total += 1
    return {
        "jobs_total": jobs_total,
        "success_total": success_total,
        "fail_total": fail_total,
        "canceled_total": canceled_total,
        "unknown_total": unknown_total,
        "updated_unix_ms": 0,
    }
