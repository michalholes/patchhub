from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from fastapi.responses import StreamingResponse

from .route_ui_snapshot import _legacy_snapshot_payload

if TYPE_CHECKING:
    from .async_app_core import AsyncAppCore
    from .snapshot_change_broker import SnapshotChangeBroker


def _snapshot_state_from_indexer(core: AsyncAppCore) -> dict[str, Any] | None:
    snap = core.indexer.get_ui_snapshot()
    if snap is None:
        return None
    return {
        "seq": int(getattr(snap, "seq", 0) or 0),
        "sigs": {
            "jobs": str(snap.jobs_sig),
            "runs": str(snap.runs_sig),
            "workspaces": str(snap.workspaces_sig),
            "header": str(snap.header_sig),
            "snapshot": str(snap.snapshot_sig),
        },
    }


async def _snapshot_state(core: AsyncAppCore) -> dict[str, Any]:
    got = _snapshot_state_from_indexer(core)
    if got is not None:
        return got
    payload = await _legacy_snapshot_payload(core)
    return {"seq": 0, "sigs": dict(payload["sigs"])}


async def build_snapshot_event_stream(
    *,
    core: AsyncAppCore,
    broker: SnapshotChangeBroker,
    ping_interval_s: float = 10.0,
) -> AsyncIterator[bytes]:
    state = await _snapshot_state(core)
    data = json.dumps(state, ensure_ascii=True)
    yield f"event: snapshot_state\ndata: {data}\n\n".encode()

    sub = broker.subscribe()
    while True:
        try:
            item = await asyncio.wait_for(sub.__anext__(), timeout=ping_interval_s)
        except StopAsyncIteration:
            return
        except TimeoutError:
            yield b": ping\n\n"
            continue
        payload = json.dumps(item, ensure_ascii=True)
        yield f"event: snapshot_changed\ndata: {payload}\n\n".encode()


async def handle_api_snapshot_events(
    core: AsyncAppCore,
    broker: SnapshotChangeBroker,
) -> StreamingResponse:
    return StreamingResponse(
        build_snapshot_event_stream(core=core, broker=broker),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
