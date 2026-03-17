# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.job_event_broker import JobEventBroker


class TestPatchhubJobEventBroker(unittest.IsolatedAsyncioTestCase):
    async def test_subscribe_replays_after_offset_then_continues_live(self) -> None:
        broker = JobEventBroker(max_replay_items=8)
        broker.publish('{"type":"log","msg":"same"}', 10)
        broker.publish('{"type":"log","msg":"same"}', 20)

        sub = broker.subscribe(after_offset=10).__aiter__()
        first = await asyncio.wait_for(sub.__anext__(), timeout=0.1)
        broker.publish('{"type":"log","msg":"next"}', 30)
        second = await asyncio.wait_for(sub.__anext__(), timeout=0.1)
        await sub.aclose()

        self.assertEqual(first, '{"type":"log","msg":"same"}')
        self.assertEqual(second, '{"type":"log","msg":"next"}')

    async def test_close_keeps_termination_signal_when_queue_is_full(self) -> None:
        broker = JobEventBroker(max_queue_items=1, max_replay_items=8)
        q: asyncio.Queue[object] = asyncio.Queue(maxsize=1)
        q.put_nowait((10, '{"type":"log","msg":"stale"}'))
        broker._subs.add(q)

        broker.close()

        self.assertIsNone(q.get_nowait())
        self.assertEqual(broker.dropped_total(), 1)

    async def test_replay_retains_20000_most_recent_items(self) -> None:
        broker = JobEventBroker()
        for idx in range(20_005):
            broker.publish(f'{{"type":"log","msg":"{idx}"}}', idx + 1)

        sub = broker.subscribe(after_offset=0).__aiter__()
        items = []
        try:
            for _ in range(20_000):
                items.append(await asyncio.wait_for(sub.__anext__(), timeout=1.0))
        finally:
            await sub.aclose()

        self.assertEqual(len(items), 20_000)
        self.assertEqual(items[0], '{"type":"log","msg":"5"}')
        self.assertEqual(items[-1], '{"type":"log","msg":"20004"}')
