from __future__ import annotations

import asyncio
from collections.abc import Callable

from .web_jobs_db import WebJobsDatabase


class WebJobsRetentionJanitor:
    def __init__(
        self,
        *,
        db: WebJobsDatabase,
        get_mode: Callable[[], str],
    ) -> None:
        self._db = db
        self._get_mode = get_mode
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._get_mode() != "db_primary":
            return
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="web-jobs-retention-janitor",
        )

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
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60 * 60)
            except TimeoutError:
                continue

    async def _tick_once(self) -> None:
        if self._get_mode() != "db_primary":
            return
        async with self._lock:
            await asyncio.to_thread(self._db.run_retention_janitor)
