from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")


async def to_thread(fn: Callable[..., _T], /, *args: object, **kwargs: object) -> _T:
    """Run blocking/sync work in a thread.

    This is the single helper used by the ASGI layer to keep the event loop
    non-blocking while reusing legacy synchronous APIs.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)
