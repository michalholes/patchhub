from __future__ import annotations

import json
from typing import Any

from fastapi.responses import Response

NO_STORE_HEADER = {"Cache-Control": "no-store"}


def json_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    merged = dict(NO_STORE_HEADER)
    if headers:
        merged.update(headers)
    return merged


def json_response(
    data: Any,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    payload = json.dumps(data, ensure_ascii=True, indent=2).encode("utf-8")
    return Response(
        content=payload,
        status_code=status,
        media_type="application/json",
        headers=json_headers(headers),
    )


def json_bytes_response(
    data: bytes,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    return Response(
        content=data,
        status_code=status,
        media_type="application/json",
        headers=json_headers(headers),
    )


def json_head_response(
    status: int,
    *,
    headers: dict[str, str] | None = None,
) -> Response:
    return Response(
        status_code=status,
        media_type="application/json",
        headers=json_headers(headers),
    )
