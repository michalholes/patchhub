# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.asgi_app import create_app
from patchhub.asgi.async_app_core import AsyncAppCore
from patchhub.asgi.async_jobs_runs_indexer import IndexerSnapshot, build_header_sig
from patchhub.asgi.operator_info_runtime import build_operator_info_sig
from patchhub.asgi.route_ui_snapshot import _legacy_snapshot_payload
from patchhub.config import load_config


async def _noop_async(self) -> None:
    return None


class _DummyIndexer:
    def __init__(self, snap: IndexerSnapshot) -> None:
        self._snap = snap

    def ready(self) -> bool:
        return True

    def get_ui_snapshot(self) -> IndexerSnapshot:
        return self._snap


class TestPatchhubUiSnapshot(unittest.TestCase):
    def test_header_sig_tracks_only_snapshot_header_payload(self) -> None:
        header_a = {
            "queue": {"queued": 1, "running": 0},
            "lock": {"path": "patches/am_patch.lock", "held": False},
            "runs": {"count": 7},
            "stats": {"all_time": {"total": 7}, "windows": []},
        }
        header_b = {
            "queue": {"queued": 1, "running": 0},
            "lock": {"path": "patches/am_patch.lock", "held": False},
            "runs": {"count": 8},
            "stats": {"all_time": {"total": 8}, "windows": []},
        }

        sig_a = build_header_sig(header_a)
        sig_a_repeat = build_header_sig(dict(header_a))
        sig_b = build_header_sig(header_b)

        self.assertEqual(sig_a, sig_a_repeat)
        self.assertNotEqual(sig_a, sig_b)

    def test_ui_snapshot_includes_workspaces_payload_and_sig(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = load_config(
                Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
            )
            snap = IndexerSnapshot(
                jobs_items=[{"job_id": "j1"}],
                runs_items=[{"issue_id": 501}],
                workspaces_items=[{"issue_id": 501, "workspace_rel_path": "workspaces/issue_501"}],
                header_body={"queue": {"queued": 0, "running": 0}},
                operator_info={
                    "cleanup_recent_status": [
                        {
                            "job_id": "job-375",
                            "issue_id": "375",
                            "created_utc": "2026-03-23T10:00:00Z",
                            "deleted_count": 1,
                            "rules": [],
                            "summary_text": "Repo snapshot cleanup: deleted 1 file(s)",
                        }
                    ]
                },
                operator_info_sig="operator_info:s1",
                jobs_sig="jobs:s1",
                runs_sig="runs:s1",
                workspaces_sig="workspaces:s1",
                header_sig="header:s1",
                snapshot_sig="snapshot:s1",
                seq=7,
            )
            try:
                with (
                    patch.object(AsyncAppCore, "startup", _noop_async),
                    patch.object(AsyncAppCore, "shutdown", _noop_async),
                ):
                    app = create_app(repo_root=root, cfg=cfg)
                    app.state.core.indexer = _DummyIndexer(snap)
                    with TestClient(app) as client:
                        resp = client.get("/api/ui_snapshot")
            except RuntimeError as exc:
                if "python-multipart" in str(exc):
                    self.skipTest(str(exc))
                raise
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("etag"), '"snapshot:s1"')
            self.assertEqual(resp.headers.get("cache-control"), "no-store")
            self.assertTrue(resp.text.startswith('{\n  "ok": true,'))
            body = resp.json()
            self.assertEqual(body["seq"], 7)
            self.assertEqual(body["snapshot"]["workspaces"], snap.workspaces_items)
            self.assertEqual(
                body["snapshot"]["operator_info"],
                snap.operator_info,
            )
            self.assertEqual(body["sigs"]["workspaces"], "workspaces:s1")
            self.assertEqual(body["sigs"]["operator_info"], "operator_info:s1")
            self.assertEqual(body["sigs"]["snapshot"], "snapshot:s1")

    def test_snapshot_sig_changes_when_operator_info_changes(self) -> None:
        payload = {"queue": {"queued": 0, "running": 0}}
        header_sig = build_header_sig(payload)
        snapshot_a = "|".join(
            [
                "jobs:s1",
                "runs:s1",
                "patches:s1",
                "workspaces:s1",
                header_sig,
                "operator_info:s1",
            ]
        )
        snapshot_b = "|".join(
            [
                "jobs:s1",
                "runs:s1",
                "patches:s1",
                "workspaces:s1",
                header_sig,
                "operator_info:s2",
            ]
        )

        self.assertNotEqual(snapshot_a, snapshot_b)

    def test_ui_snapshot_returns_304_for_matching_etag(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = load_config(
                Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
            )
            snap = IndexerSnapshot(
                jobs_items=[],
                runs_items=[],
                workspaces_items=[],
                header_body={},
                operator_info={"cleanup_recent_status": []},
                operator_info_sig="operator_info:s2",
                jobs_sig="jobs:s2",
                runs_sig="runs:s2",
                workspaces_sig="workspaces:s2",
                header_sig="header:s2",
                snapshot_sig="snapshot:s2",
            )
            try:
                with (
                    patch.object(AsyncAppCore, "startup", _noop_async),
                    patch.object(AsyncAppCore, "shutdown", _noop_async),
                ):
                    app = create_app(repo_root=root, cfg=cfg)
                    app.state.core.indexer = _DummyIndexer(snap)
                    with TestClient(app) as client:
                        resp = client.get(
                            "/api/ui_snapshot",
                            headers={"If-None-Match": '"snapshot:s2"'},
                        )
            except RuntimeError as exc:
                if "python-multipart" in str(exc):
                    self.skipTest(str(exc))
                raise
            self.assertEqual(resp.status_code, 304)
            self.assertEqual(resp.headers.get("etag"), '"snapshot:s2"')
            self.assertEqual(resp.headers.get("cache-control"), "no-store")
            self.assertEqual(resp.text, "")

    def test_legacy_snapshot_payload_includes_seq(self) -> None:
        class _DummyQueue:
            async def state(self) -> object:
                return type("QState", (), {"queued": 0, "running": 0})()

            async def list_jobs(self) -> list[object]:
                return []

        class _DummyIndexer:
            def snapshot_seq(self) -> int:
                return 9

        class _DummyCore:
            def __init__(self) -> None:
                self.queue = _DummyQueue()
                self.indexer = _DummyIndexer()
                self.jobs_root = Path(".")
                self.patches_root = Path(".")
                self.cfg = type(
                    "Cfg",
                    (),
                    {
                        "paths": type("Paths", (), {"patches_root": "patches"})(),
                        "indexing": type(
                            "Indexing",
                            (),
                            {
                                "log_filename_regex": r"am_patch_issue_(\d+)_",
                                "stats_windows_days": [7, 30],
                            },
                        )(),
                    },
                )()

            def _load_job_from_disk(self, _job_id: str) -> None:
                return None

            def api_runs(self, _query: dict[str, str]) -> tuple[int, bytes]:
                return 200, b'{"runs": []}'

        core = _DummyCore()
        with (
            patch(
                "patchhub.asgi.route_ui_snapshot.legacy_jobs_signature",
                return_value=(0, 0),
            ),
            patch("patchhub.asgi.route_ui_snapshot.runs_signature", return_value=(0, 0, 0)),
            patch(
                "patchhub.asgi.route_ui_snapshot.canceled_runs_signature",
                return_value=(0, 0),
            ),
            patch("patchhub.asgi.route_ui_snapshot.list_legacy_job_jsons", return_value=[]),
            patch(
                "patchhub.asgi.route_ui_snapshot.list_workspaces",
                return_value=("workspaces:s0", []),
            ),
            patch("patchhub.asgi.route_ui_snapshot.iter_runs", return_value=[]),
        ):
            payload = asyncio.run(_legacy_snapshot_payload(cast(AsyncAppCore, core)))

        self.assertEqual(payload["seq"], 9)
        self.assertEqual(payload["snapshot"]["jobs"], [])
        self.assertEqual(payload["snapshot"]["runs"], [])
        self.assertEqual(
            payload["snapshot"]["operator_info"],
            {
                "cleanup_recent_status": [],
                "backend_mode_status": {
                    "mode": "",
                    "authoritative_backend": "",
                    "backend_session_id": "",
                    "recovery_status": "not_run",
                    "recovery_action": "",
                    "recovery_detail": "",
                    "degraded": False,
                },
            },
        )
        self.assertIn("operator_info", payload["sigs"])

    def test_operator_info_sig_changes_when_backend_status_changes(self) -> None:
        payload_a = {
            "cleanup_recent_status": [],
            "backend_mode_status": {
                "mode": "db_primary",
                "authoritative_backend": "db",
                "backend_session_id": "session-a",
                "recovery_status": "ok",
                "recovery_action": "main_db",
                "recovery_detail": "validated",
                "degraded": False,
            },
        }
        payload_b = {
            "cleanup_recent_status": [],
            "backend_mode_status": {
                "mode": "file_emergency",
                "authoritative_backend": "files",
                "backend_session_id": "session-b",
                "recovery_status": "fallback",
                "recovery_action": "fallback_export",
                "recovery_detail": "legacy-tree",
                "degraded": True,
            },
        }

        self.assertNotEqual(build_operator_info_sig(payload_a), build_operator_info_sig(payload_b))
