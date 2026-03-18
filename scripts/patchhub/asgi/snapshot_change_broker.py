from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any


class SnapshotChangeBroker:
    def __init__(self, *, max_queue_items: int = 64) -> None:
        self._max_queue_items = max(1, int(max_queue_items))
        self._mu = asyncio.Lock()
        self._subs: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._closed = False

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=self._max_queue_items)
        async with self._mu:
            if self._closed:
                return
            self._subs.add(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    return
                yield item
        finally:
            async with self._mu:
                self._subs.discard(q)

    def publish(self, payload: dict[str, Any]) -> None:
        if self._closed:
            return
        item = dict(payload)
        for q in list(self._subs):
            while True:
                try:
                    q.put_nowait(item)
                    break
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for q in list(self._subs):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                with suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                with suppress(asyncio.QueueFull):
                    q.put_nowait(None)
        self._subs.clear()
