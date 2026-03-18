# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.asgi_app import create_app
from patchhub.asgi.async_app_core import AsyncAppCore
from patchhub.config import load_config


async def _noop_async(self) -> None:
    return None


class _QueueOk:
    async def hard_stop(self, job_id: str) -> bool:
        del job_id
        return True


class _QueueFail:
    async def hard_stop(self, job_id: str) -> bool:
        del job_id
        return False


class TestPatchhubHardStopApi(unittest.TestCase):
    def test_hard_stop_endpoint_returns_409_when_queue_rejects(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = load_config(
                Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
            )
            with (
                patch.object(AsyncAppCore, "startup", _noop_async),
                patch.object(AsyncAppCore, "shutdown", _noop_async),
            ):
                app = create_app(repo_root=root, cfg=cfg)
                app.state.core.queue = _QueueFail()
                with TestClient(app) as client:
                    resp = client.post("/api/jobs/job-700/hard_stop")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"], "Cannot hard stop")

    def test_hard_stop_endpoint_returns_200_when_queue_accepts(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = load_config(
                Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
            )
            with (
                patch.object(AsyncAppCore, "startup", _noop_async),
                patch.object(AsyncAppCore, "shutdown", _noop_async),
            ):
                app = create_app(repo_root=root, cfg=cfg)
                app.state.core.queue = _QueueOk()
                with TestClient(app) as client:
                    resp = client.post("/api/jobs/job-701/hard_stop")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])


def test_progress_ui_exposes_cancel_and_hard_stop_actions() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "patchhub"
        / "static"
        / "patchhub_progress_ui.js"
    ).read_text(encoding="utf-8")
    assert "cancelActive" in script
    assert "hardStopActive" in script
    assert "Hard stop AMP" in script
    assert "/hard_stop" in script
