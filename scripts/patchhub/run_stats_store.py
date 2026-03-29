from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .indexing import iter_run_log_infos, read_run_result_from_log
from .models import AppStats, StatsWindow, WebJobsDbConfig

_RESULT_VALUES = ("success", "fail", "unknown")


@dataclass(frozen=True)
class RunStatsMeta:
    last_indexed_mtime_ns: int
    last_indexed_filename: str
    all_time_total: int
    all_time_success: int
    all_time_fail: int
    all_time_unknown: int


@dataclass(frozen=True)
class RunStatsSummary:
    count: int
    stats: AppStats


class RunStatsStore:
    def __init__(self, cfg: WebJobsDbConfig, patches_root: Path) -> None:
        self.cfg = cfg
        self.patches_root = patches_root
        self.cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

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

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_stats_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    last_indexed_mtime_ns INTEGER NOT NULL DEFAULT 0,
                    last_indexed_filename TEXT NOT NULL DEFAULT '',
                    all_time_total INTEGER NOT NULL DEFAULT 0,
                    all_time_success INTEGER NOT NULL DEFAULT 0,
                    all_time_fail INTEGER NOT NULL DEFAULT 0,
                    all_time_unknown INTEGER NOT NULL DEFAULT 0,
                    updated_unix_ms INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_stats_seen (
                    source_key TEXT PRIMARY KEY,
                    log_rel_path TEXT NOT NULL,
                    log_mtime_ns INTEGER NOT NULL,
                    log_size INTEGER NOT NULL DEFAULT 0,
                    run_unix_ms INTEGER NOT NULL,
                    result TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_run_stats_seen_run_unix_ms
                    ON run_stats_seen(run_unix_ms)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_run_stats_seen_log_mtime_ns
                    ON run_stats_seen(log_mtime_ns, log_rel_path)
                """
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
                (_utc_now_ms(),),
            )

    def ingest_logs(self, log_filename_regex: str) -> None:
        candidates = iter_run_log_infos(self.patches_root, log_filename_regex)
        if not candidates:
            return
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            meta = self._load_meta(conn)
            processed = False
            for log_path, _issue_id, mtime_s, mtime_ns, log_size in candidates:
                name = log_path.name
                if not self._is_after_cursor(meta, mtime_ns=mtime_ns, filename=name):
                    continue
                rel_path = str(Path("logs") / name)
                source_key = rel_path
                result, _result_line = read_run_result_from_log(
                    log_path,
                    log_mtime_ns=mtime_ns,
                )
                run_unix_ms = int(mtime_s * 1000)
                meta = self._upsert_seen_row(
                    conn,
                    meta,
                    source_key=source_key,
                    log_rel_path=rel_path,
                    log_mtime_ns=mtime_ns,
                    log_size=log_size,
                    run_unix_ms=run_unix_ms,
                    result=result,
                )
                meta = RunStatsMeta(
                    last_indexed_mtime_ns=int(mtime_ns),
                    last_indexed_filename=name,
                    all_time_total=meta.all_time_total,
                    all_time_success=meta.all_time_success,
                    all_time_fail=meta.all_time_fail,
                    all_time_unknown=meta.all_time_unknown,
                )
                processed = True
            if processed:
                self._write_meta(conn, meta)
            conn.commit()

    def build_summary(
        self,
        windows_days: list[int],
        *,
        now_unix_ms: int | None = None,
    ) -> RunStatsSummary:
        current_ms = int(now_unix_ms) if now_unix_ms is not None else _utc_now_ms()
        with self._connect() as conn:
            meta = self._load_meta(conn)
            windows = [
                self._query_window(conn, current_ms=current_ms, days=int(days))
                for days in windows_days
            ]
        return RunStatsSummary(
            count=meta.all_time_total,
            stats=AppStats(
                all_time=StatsWindow(
                    days=0,
                    total=meta.all_time_total,
                    success=meta.all_time_success,
                    fail=meta.all_time_fail,
                    unknown=meta.all_time_unknown,
                ),
                windows=windows,
            ),
        )

    def _query_window(
        self,
        conn: sqlite3.Connection,
        *,
        current_ms: int,
        days: int,
    ) -> StatsWindow:
        cutoff_ms = int(current_ms - (days * 86400 * 1000))
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN result = 'success' THEN 1 ELSE 0 END) AS success,
                SUM(CASE WHEN result = 'fail' THEN 1 ELSE 0 END) AS fail,
                SUM(CASE WHEN result = 'unknown' THEN 1 ELSE 0 END) AS unknown
              FROM run_stats_seen
             WHERE run_unix_ms >= ?
            """,
            (cutoff_ms,),
        ).fetchone()
        return StatsWindow(
            days=int(days),
            total=int(row["total"] or 0),
            success=int(row["success"] or 0),
            fail=int(row["fail"] or 0),
            unknown=int(row["unknown"] or 0),
        )

    def _load_meta(self, conn: sqlite3.Connection) -> RunStatsMeta:
        row = conn.execute(
            """
            SELECT
                last_indexed_mtime_ns,
                last_indexed_filename,
                all_time_total,
                all_time_success,
                all_time_fail,
                all_time_unknown
              FROM run_stats_meta
             WHERE singleton = 1
            """
        ).fetchone()
        if row is None:
            return RunStatsMeta(0, "", 0, 0, 0, 0)
        return RunStatsMeta(
            last_indexed_mtime_ns=int(row["last_indexed_mtime_ns"] or 0),
            last_indexed_filename=str(row["last_indexed_filename"] or ""),
            all_time_total=int(row["all_time_total"] or 0),
            all_time_success=int(row["all_time_success"] or 0),
            all_time_fail=int(row["all_time_fail"] or 0),
            all_time_unknown=int(row["all_time_unknown"] or 0),
        )

    def _write_meta(self, conn: sqlite3.Connection, meta: RunStatsMeta) -> None:
        conn.execute(
            """
            UPDATE run_stats_meta
               SET last_indexed_mtime_ns = ?,
                   last_indexed_filename = ?,
                   all_time_total = ?,
                   all_time_success = ?,
                   all_time_fail = ?,
                   all_time_unknown = ?,
                   updated_unix_ms = ?
             WHERE singleton = 1
            """,
            (
                meta.last_indexed_mtime_ns,
                meta.last_indexed_filename,
                meta.all_time_total,
                meta.all_time_success,
                meta.all_time_fail,
                meta.all_time_unknown,
                _utc_now_ms(),
            ),
        )

    def _upsert_seen_row(
        self,
        conn: sqlite3.Connection,
        meta: RunStatsMeta,
        *,
        source_key: str,
        log_rel_path: str,
        log_mtime_ns: int,
        log_size: int,
        run_unix_ms: int,
        result: str,
    ) -> RunStatsMeta:
        existing = conn.execute(
            """
            SELECT result, log_mtime_ns, log_size, run_unix_ms
              FROM run_stats_seen
             WHERE source_key = ?
            """,
            (str(source_key),),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO run_stats_seen(
                    source_key,
                    log_rel_path,
                    log_mtime_ns,
                    log_size,
                    run_unix_ms,
                    result
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(source_key),
                    str(log_rel_path),
                    int(log_mtime_ns),
                    int(log_size),
                    int(run_unix_ms),
                    str(result),
                ),
            )
            return _apply_delta(meta, old_result=None, new_result=result)

        old_result = str(existing["result"] or "unknown")
        old_mtime_ns = int(existing["log_mtime_ns"] or 0)
        old_size = int(existing["log_size"] or 0)
        old_run_unix_ms = int(existing["run_unix_ms"] or 0)
        if (
            old_result == result
            and old_mtime_ns == int(log_mtime_ns)
            and old_size == int(log_size)
            and old_run_unix_ms == int(run_unix_ms)
        ):
            return meta

        conn.execute(
            """
            UPDATE run_stats_seen
               SET log_rel_path = ?,
                   log_mtime_ns = ?,
                   log_size = ?,
                   run_unix_ms = ?,
                   result = ?
             WHERE source_key = ?
            """,
            (
                str(log_rel_path),
                int(log_mtime_ns),
                int(log_size),
                int(run_unix_ms),
                str(result),
                str(source_key),
            ),
        )
        return _apply_delta(meta, old_result=old_result, new_result=result)

    def _is_after_cursor(
        self,
        meta: RunStatsMeta,
        *,
        mtime_ns: int,
        filename: str,
    ) -> bool:
        current = (int(mtime_ns), str(filename))
        cursor = (int(meta.last_indexed_mtime_ns), str(meta.last_indexed_filename))
        return current > cursor


def _apply_delta(
    meta: RunStatsMeta,
    *,
    old_result: str | None,
    new_result: str,
) -> RunStatsMeta:
    total = meta.all_time_total
    success = meta.all_time_success
    fail = meta.all_time_fail
    unknown = meta.all_time_unknown
    if old_result is None:
        total += 1
    elif old_result == new_result:
        return meta
    else:
        if old_result == "success":
            success -= 1
        elif old_result == "fail":
            fail -= 1
        else:
            unknown -= 1
    if new_result == "success":
        success += 1
    elif new_result == "fail":
        fail += 1
    else:
        unknown += 1
    return RunStatsMeta(
        last_indexed_mtime_ns=meta.last_indexed_mtime_ns,
        last_indexed_filename=meta.last_indexed_filename,
        all_time_total=total,
        all_time_success=success,
        all_time_fail=fail,
        all_time_unknown=unknown,
    )


def _utc_now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)
