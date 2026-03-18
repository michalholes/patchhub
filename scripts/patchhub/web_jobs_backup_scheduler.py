from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import WebJobsDbConfig
from .web_jobs_backup import (
    WebJobsBackupSettings,
    create_verified_backup,
    load_web_jobs_backup_settings,
)
from .web_jobs_recovery import read_runtime_state, record_verified_backup


def _parse_utc(raw: object) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def interval_backup_due(
    settings: WebJobsBackupSettings,
    *,
    state: dict[str, object],
    now: datetime,
) -> bool:
    if not settings.enabled or settings.trigger_policy != "interval_hours":
        return False
    last = _parse_utc(state.get("last_verified_backup_utc"))
    if last is None:
        return True
    return now >= last + timedelta(hours=settings.interval_hours)


def maybe_create_interval_backup_once(
    *,
    repo_root: Path,
    patches_root: Path,
    db_cfg: WebJobsDbConfig,
    mode: str,
) -> Path | None:
    settings = load_web_jobs_backup_settings(repo_root, patches_root, db_cfg)
    if mode != "db_primary" or not settings.enabled:
        return None
    if settings.trigger_policy != "interval_hours":
        return None
    state = read_runtime_state(patches_root)
    now = datetime.now(UTC)
    if not interval_backup_due(settings, state=state, now=now):
        return None
    result = create_verified_backup(
        db_path=db_cfg.db_path,
        patches_root=patches_root,
        settings=settings,
    )
    record_verified_backup(patches_root, backup_path=result.path)
    return result.path


class WebJobsBackupScheduler:
    def __init__(
        self,
        *,
        repo_root: Path,
        patches_root: Path,
        db_cfg: WebJobsDbConfig,
        get_mode: Callable[[], str],
    ) -> None:
        self._repo_root = repo_root
        self._patches_root = patches_root
        self._db_cfg = db_cfg
        self._get_mode = get_mode
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        settings = load_web_jobs_backup_settings(
            self._repo_root,
            self._patches_root,
            self._db_cfg,
        )
        if not settings.enabled or settings.trigger_policy != "interval_hours":
            return
        if self._get_mode() != "db_primary":
            return
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="web-jobs-backup-scheduler")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        await task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            await self._tick_once()
            settings = load_web_jobs_backup_settings(
                self._repo_root,
                self._patches_root,
                self._db_cfg,
            )
            timeout_s = max(1, int(settings.check_interval_minutes) * 60)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=timeout_s)
            except TimeoutError:
                continue

    async def _tick_once(self) -> None:
        if self._get_mode() != "db_primary":
            return
        async with self._lock:
            await asyncio.to_thread(
                maybe_create_interval_backup_once,
                repo_root=self._repo_root,
                patches_root=self._patches_root,
                db_cfg=self._db_cfg,
                mode=self._get_mode(),
            )
