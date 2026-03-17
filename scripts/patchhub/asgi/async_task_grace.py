from __future__ import annotations

import asyncio
import contextlib


async def wait_with_grace(task: asyncio.Task[object], *, grace_s: int) -> bool:
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=max(1, int(grace_s)))
        return False
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True


async def cancel_and_wait(task: asyncio.Task[object] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
