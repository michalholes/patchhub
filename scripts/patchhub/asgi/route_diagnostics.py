from __future__ import annotations

import json
from hashlib import sha1
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.responses import Response

if TYPE_CHECKING:
    from .async_app_core import AsyncAppCore


def _etag_quote(token: str) -> str:
    token = str(token or "")
    return '"' + token.replace('"', "") + '"'


def _etag_matches(if_none_match: str | None, etag_value: str) -> bool:
    if if_none_match is None:
        return False
    return str(if_none_match).strip() == etag_value


def _diagnostics_sig(body: dict[str, Any]) -> str:
    payload = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "diag:" + sha1(payload).hexdigest()


async def handle_api_debug_diagnostics(core: AsyncAppCore, request: Request) -> Response:
    since_sig = str(request.query_params.get("since_sig", "")).strip()
    body = await core.diagnostics()
    sig = _diagnostics_sig(body)
    etag = _etag_quote(sig)

    inm = request.headers.get("if-none-match")
    if etag and _etag_matches(inm, etag):
        return Response(status_code=304, headers={"ETag": etag})

    if since_sig and since_sig == sig:
        data = json.dumps(
            {"ok": True, "unchanged": True, "sig": sig},
            ensure_ascii=True,
        ).encode("utf-8")
        return Response(
            content=data,
            status_code=200,
            media_type="application/json",
            headers={"ETag": etag},
        )

    data = json.dumps(body, ensure_ascii=True).encode("utf-8")
    return Response(
        content=data,
        status_code=200,
        media_type="application/json",
        headers={"ETag": etag},
    )
