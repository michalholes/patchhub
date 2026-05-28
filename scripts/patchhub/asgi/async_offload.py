from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")


async def to_thread(fn: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Run blocking/sync work in a thread.

    This is the single helper used by the ASGI layer to keep the event loop
    non-blocking while reusing legacy synchronous APIs.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)
