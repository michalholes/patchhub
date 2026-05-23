# ruff: noqa: E402
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from starlette.requests import Request

from patchhub.asgi.route_diagnostics import handle_api_debug_diagnostics


class _DummyCore:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = body

    async def diagnostics(self) -> dict[str, object]:
        return dict(self._body)


def _request(*, since_sig: str = "", if_none_match: str = "") -> Request:
    query = "" if not since_sig else f"since_sig={since_sig}"
    headers: list[tuple[bytes, bytes]] = []
    if if_none_match:
        headers.append((b"if-none-match", if_none_match.encode("utf-8")))

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/debug/diagnostics",
        "raw_path": b"/api/debug/diagnostics",
        "query_string": query.encode("utf-8"),
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


class TestPatchhubRouteDiagnostics(unittest.TestCase):
    def test_returns_304_for_matching_etag(self) -> None:
        core = _DummyCore(
            {
                "queue": {"queued": 0, "running": 0},
                "lock": {"path": "patches/am_patch.lock", "held": False},
                "disk": {"total": 100, "used": 50, "free": 50},
                "runs": {"count": 3},
                "stats": {"all_time": {}, "windows": []},
                "resources": {},
            }
        )
        first = asyncio.run(handle_api_debug_diagnostics(core, _request()))
        etag = str(first.headers.get("etag") or "")
        self.assertTrue(etag)
        second = asyncio.run(handle_api_debug_diagnostics(core, _request(if_none_match=etag)))
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.headers.get("etag"), etag)

    def test_returns_unchanged_for_matching_since_sig(self) -> None:
        core = _DummyCore(
            {
                "queue": {"queued": 1, "running": 0},
                "lock": {"path": "patches/am_patch.lock", "held": True},
                "disk": {"total": 100, "used": 60, "free": 40},
                "runs": {"count": 4},
                "stats": {"all_time": {}, "windows": []},
                "resources": {"host": {"loadavg_1": 0.5}},
            }
        )
        first = asyncio.run(handle_api_debug_diagnostics(core, _request()))
        etag = str(first.headers.get("etag") or "")
        self.assertTrue(etag.startswith('"diag:'))
        sig = etag.strip('"')
        second = asyncio.run(handle_api_debug_diagnostics(core, _request(since_sig=sig)))
        self.assertEqual(second.status_code, 200)
        body = json.loads(second.body.decode("utf-8"))
        self.assertEqual(body, {"ok": True, "unchanged": True, "sig": sig})
