from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import Response

if TYPE_CHECKING:
    from .snapshot_delta_store import SnapshotDeltaStore


async def handle_api_ui_snapshot_delta(
    request: Request,
    delta_store: SnapshotDeltaStore,
) -> Response:
    raw = str(request.query_params.get("since_seq", "")).strip()
    try:
        since_seq = int(raw)
    except Exception:
        since_seq = -1
    payload = delta_store.build_delta(since_seq)
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    return Response(content=data, status_code=200, media_type="application/json")
