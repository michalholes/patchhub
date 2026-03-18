# ruff: noqa: E402
from __future__ import annotations

import json
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


class _DummyIndexer:
    def ready(self) -> bool:
        return False


class TestPatchhubAsgiRunsContract(unittest.TestCase):
    def test_api_runs_fallback_returns_etag_no_store_and_pretty_json(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = load_config(
                Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
            )
            try:
                with (
                    patch.object(AsyncAppCore, "startup", _noop_async),
                    patch.object(AsyncAppCore, "shutdown", _noop_async),
                ):
                    app = create_app(repo_root=root, cfg=cfg)
                    app.state.core.indexer = _DummyIndexer()
                    app.state.core.jobs_root = root / "patches" / "artifacts" / "web_jobs"
                    app.state.core.web_jobs_db = None
                    app.state.core.api_runs = lambda _qs: (
                        200,
                        json.dumps(
                            {"ok": True, "runs": [], "sig": "runs:r=1:2:3:c=4:5"},
                            ensure_ascii=True,
                            indent=2,
                        ).encode("utf-8"),
                    )
                    with (
                        patch("patchhub.indexing.runs_signature", return_value=(1, 2, 3)),
                        patch(
                            "patchhub.app_support.canceled_runs_signature",
                            return_value=(4, 5),
                        ),
                        TestClient(app) as client,
                    ):
                        resp = client.get("/api/runs")
            except RuntimeError as exc:
                if "python-multipart" in str(exc):
                    self.skipTest(str(exc))
                raise
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("etag"), '"runs:r=1:2:3:c=4:5"')
        self.assertEqual(resp.headers.get("cache-control"), "no-store")
        self.assertTrue(resp.text.startswith('{\n  "ok": true,'))
