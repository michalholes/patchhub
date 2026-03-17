# ruff: noqa: E402
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

from starlette.requests import Request

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.async_jobs_runs_indexer import IndexerSnapshot
from patchhub.asgi.route_ui_snapshot_delta import handle_api_ui_snapshot_delta
from patchhub.asgi.snapshot_delta_store import SnapshotDeltaStore


class TestPatchhubUiSnapshotDelta(unittest.TestCase):
    def _snap(
        self,
        *,
        seq: int,
        job_status: str = "queued",
        header_count: int = 1,
        include_workspace: bool = True,
        include_run: bool = True,
    ) -> IndexerSnapshot:
        jobs = [
            {
                "job_id": "job-1",
                "status": job_status,
                "issue_id": 500,
            }
        ]
        runs = (
            [
                {
                    "issue_id": 500,
                    "mtime_utc": "2026-03-08T10:00:00Z",
                    "result": "success",
                }
            ]
            if include_run
            else []
        )
        workspaces = (
            [
                {
                    "issue_id": 500,
                    "workspace_rel_path": "ws/500/a",
                    "state": "clean",
                }
            ]
            if include_workspace
            else []
        )
        return IndexerSnapshot(
            jobs_items=jobs,
            runs_items=runs,
            workspaces_items=workspaces,
            header_body={"runs": {"count": header_count}},
            jobs_sig=f"jobs:s{seq}",
            runs_sig=f"runs:s{seq}",
            workspaces_sig=f"workspaces:s{seq}",
            header_sig=f"header:s{seq}",
            snapshot_sig=f"snapshot:s{seq}",
            seq=seq,
        )

    def test_delta_store_tracks_added_updated_removed_and_header_change(self) -> None:
        store = SnapshotDeltaStore()
        store.record_snapshot(self._snap(seq=1))
        store.record_snapshot(
            self._snap(
                seq=2,
                job_status="running",
                header_count=2,
                include_workspace=False,
                include_run=False,
            )
        )

        delta = store.build_delta(1)
        self.assertTrue(delta["ok"])
        self.assertEqual(delta["seq"], 2)
        self.assertEqual(delta["jobs"]["updated"][0]["status"], "running")
        self.assertEqual(delta["runs"]["removed"][0]["issue_id"], 500)
        self.assertEqual(
            delta["workspaces"]["removed"][0]["workspace_rel_path"],
            "ws/500/a",
        )
        self.assertTrue(delta["header_changed"])
        self.assertEqual(delta["header"]["runs"]["count"], 2)

    def test_delta_store_requires_resync_for_stale_seq(self) -> None:
        store = SnapshotDeltaStore(max_records=2)
        store.record_snapshot(self._snap(seq=1))
        store.record_snapshot(self._snap(seq=2))
        store.record_snapshot(self._snap(seq=3))

        delta = store.build_delta(1)
        self.assertTrue(delta["ok"])
        self.assertTrue(delta["resync_needed"])
        self.assertEqual(delta["seq"], 3)

    def test_route_returns_json_payload(self) -> None:
        store = SnapshotDeltaStore()
        store.record_snapshot(self._snap(seq=1))
        store.record_snapshot(self._snap(seq=2, job_status="running"))

        async def _call() -> dict[str, object]:
            async def _recv() -> dict[str, object]:
                return {"type": "http.request", "body": b"", "more_body": False}

            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/ui_snapshot_delta",
                    "query_string": b"since_seq=1",
                    "headers": [],
                },
                _recv,
            )
            response = await handle_api_ui_snapshot_delta(request, store)
            return json.loads(response.body.decode("utf-8"))

        payload = asyncio.run(_call())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["seq"], 2)
        self.assertEqual(payload["jobs"]["updated"][0]["status"], "running")

    def test_delta_store_omits_header_when_header_is_unchanged(self) -> None:
        store = SnapshotDeltaStore()
        store.record_snapshot(self._snap(seq=1, header_count=1))
        store.record_snapshot(self._snap(seq=2, header_count=1, job_status="running"))

        delta = store.build_delta(1)
        self.assertTrue(delta["ok"])
        self.assertFalse(delta["header_changed"])
        self.assertNotIn("header", delta)
