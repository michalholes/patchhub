from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import Response

from .async_offload import to_thread
from .json_contract import json_bytes_response, json_headers, json_response

if TYPE_CHECKING:
    from .async_app_core import AsyncAppCore


def _etag_quote(token: str) -> str:
    token = str(token or "")
    return '"' + token.replace('"', "") + '"'


def _etag_matches(if_none_match: str | None, etag_value: str) -> bool:
    if if_none_match is None:
        return False
    inm = str(if_none_match).strip()
    return inm == etag_value


async def handle_api_workspaces(core: AsyncAppCore, request: Request) -> Response:
    since_sig = str(request.query_params.get("since_sig", "")).strip()

    if core.indexer.ready():
        snap = core.indexer.get_ui_snapshot()
        if snap is not None:
            sig = str(snap.workspaces_sig)
            etag = _etag_quote(sig)
            inm = request.headers.get("if-none-match")
            if etag and _etag_matches(inm, etag):
                return Response(status_code=304, headers=json_headers({"ETag": etag}))
            if since_sig and since_sig == sig:
                return json_response(
                    {"ok": True, "unchanged": True, "sig": sig},
                    status=200,
                    headers={"ETag": etag},
                )
            return json_response(
                {
                    "ok": True,
                    "items": list(snap.workspaces_items),
                    "sig": sig,
                },
                status=200,
                headers={"ETag": etag},
            )

    mem = await core.queue.list_jobs()
    status, data = await to_thread(core.api_workspaces, mem)
    etag = ""
    try:
        obj = json.loads(data.decode("utf-8"))
        token = str(obj.get("sig", ""))
        if token:
            etag = _etag_quote(token)
    except Exception:
        etag = ""
    inm = request.headers.get("if-none-match")
    if status == 200 and etag and _etag_matches(inm, etag):
        return Response(status_code=304, headers=json_headers({"ETag": etag}))
    if status == 200 and since_sig:
        try:
            obj = json.loads(data.decode("utf-8"))
            token = str(obj.get("sig", ""))
        except Exception:
            token = ""
        if token and token == since_sig:
            return json_response(
                {"ok": True, "unchanged": True, "sig": token},
                status=200,
                headers={"ETag": etag} if etag else None,
            )
    headers = {"ETag": etag} if (status == 200 and etag) else None
    return json_bytes_response(data, status=status, headers=headers)
