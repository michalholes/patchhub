# ruff: noqa: E402
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.async_jobs_runs_indexer import IndexerSnapshot
from patchhub.asgi.route_snapshot_events import build_snapshot_event_stream
from patchhub.asgi.snapshot_change_broker import SnapshotChangeBroker


class _DummyIndexer:
    def __init__(self, snap: IndexerSnapshot | None) -> None:
        self._snap = snap

    def get_ui_snapshot(self) -> IndexerSnapshot | None:
        return self._snap


class _DummyCore:
    def __init__(self, snap: IndexerSnapshot | None) -> None:
        self.indexer = _DummyIndexer(snap)


class TestPatchhubSnapshotEvents(unittest.TestCase):
    def test_stream_sends_initial_snapshot_state_then_change(self) -> None:
        snap = IndexerSnapshot(
            jobs_items=[],
            runs_items=[],
            workspaces_items=[],
            header_body={},
            jobs_sig="jobs:s1",
            runs_sig="runs:s1",
            workspaces_sig="workspaces:s1",
            header_sig="header:s1",
            snapshot_sig="snapshot:s1",
            seq=7,
        )
        core = _DummyCore(snap)
        broker = SnapshotChangeBroker()

        async def _collect() -> list[bytes]:
            stream = build_snapshot_event_stream(core=core, broker=broker, ping_interval_s=60.0)
            first = await stream.__anext__()

            async def _publish_soon() -> None:
                await asyncio.sleep(0.01)
                broker.publish(
                    {
                        "seq": 8,
                        "sigs": {
                            "jobs": "jobs:s2",
                            "runs": "runs:s2",
                            "workspaces": "workspaces:s2",
                            "header": "header:s2",
                            "snapshot": "snapshot:s2",
                        },
                    }
                )

            asyncio.create_task(_publish_soon())
            second = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
            return [first, second]

        first, second = asyncio.run(_collect())
        self.assertIn(b"event: snapshot_state", first)
        self.assertIn(b"event: snapshot_changed", second)
        body = json.loads(second.decode("utf-8").split("data: ", 1)[1])
        self.assertEqual(body["seq"], 8)
        self.assertEqual(body["sigs"]["snapshot"], "snapshot:s2")
