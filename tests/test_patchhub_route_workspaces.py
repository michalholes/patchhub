# ruff: noqa: E402
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from starlette.requests import Request

from patchhub.asgi.async_jobs_runs_indexer import IndexerSnapshot
from patchhub.asgi.route_workspaces import handle_api_workspaces


class _DummyIndexer:
    def __init__(self, snap: IndexerSnapshot | None) -> None:
        self._snap = snap

    def ready(self) -> bool:
        return self._snap is not None

    def get_ui_snapshot(self) -> IndexerSnapshot | None:
        return self._snap


class _DummyQueue:
    def __init__(self, jobs: list[object] | None = None) -> None:
        self._jobs = list(jobs or [])

    async def list_jobs(self) -> list[object]:
        return list(self._jobs)


@dataclass
class _DummyCore:
    indexer: _DummyIndexer
    queue: _DummyQueue
    workspaces_payload: dict[str, object] | None = None

    def api_workspaces(self, mem_jobs: list[object]) -> tuple[int, bytes]:
        payload = dict(self.workspaces_payload or {})
        payload.setdefault("ok", True)
        payload.setdefault("items", [])
        payload.setdefault("sig", "workspaces:fallback")
        return 200, json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")


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
        "path": "/api/workspaces",
        "raw_path": b"/api/workspaces",
        "query_string": query.encode("utf-8"),
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


class TestPatchhubRouteWorkspaces(unittest.TestCase):
    def test_indexer_path_returns_304_for_matching_etag(self) -> None:
        snap = IndexerSnapshot(
            jobs_items=[],
            runs_items=[],
            workspaces_items=[{"issue_id": 501}],
            header_body={},
            jobs_sig="jobs:sig",
            runs_sig="runs:sig",
            workspaces_sig="workspaces:sig501",
            header_sig="header:sig",
            snapshot_sig="snapshot:sig",
        )
        core = _DummyCore(indexer=_DummyIndexer(snap), queue=_DummyQueue())
        response = asyncio.run(
            handle_api_workspaces(
                core,
                _request(if_none_match='"workspaces:sig501"'),
            )
        )
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.headers.get("etag"), '"workspaces:sig501"')
        self.assertEqual(response.headers.get("cache-control"), "no-store")

    def test_fallback_returns_unchanged_for_matching_since_sig(self) -> None:
        core = _DummyCore(
            indexer=_DummyIndexer(None),
            queue=_DummyQueue(),
            workspaces_payload={
                "items": [{"issue_id": 777}],
                "sig": "workspaces:fallback777",
            },
        )
        response = asyncio.run(
            handle_api_workspaces(
                core,
                _request(since_sig="workspaces:fallback777"),
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("etag"), '"workspaces:fallback777"')
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertTrue(response.body.decode("utf-8").startswith('{\n  "ok": true,'))
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "ok": True,
                "unchanged": True,
                "sig": "workspaces:fallback777",
            },
        )
