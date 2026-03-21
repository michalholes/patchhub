from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


def _get_web_interface_plugin_cls() -> type:
    """Import the web_interface plugin in a pytest-collection-safe way."""

    # Ensure repository root is importable for 'plugins.*' imports.
    repo_root = Path(__file__).resolve().parents[2]
    repo_root_s = str(repo_root)
    if repo_root_s not in sys.path:
        sys.path.insert(0, repo_root_s)

    from plugins.web_interface.core import WebInterfacePlugin

    return WebInterfacePlugin


def _make_client(app: Any) -> Any:
    pytest.importorskip("httpx")  # required by fastapi/starlette TestClient
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_web_jobs_api_create_list_cancel(tmp_path: Path, monkeypatch: Any) -> None:
    # Isolate HOME so jobs persist under tmp_path, not the real user home.
    monkeypatch.setenv("HOME", str(tmp_path))

    web_interface_plugin_cls = _get_web_interface_plugin_cls()
    app = web_interface_plugin_cls().create_app()
    client = _make_client(app)

    # Create a pending job (no execution).
    resp = client.post(
        "/api/jobs/process",
        json={"pipeline_path": "pipelines/example.yaml", "sources": ["a.mp3"]},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # List should include it.
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    items = resp.json().get("items", [])
    assert any(it.get("job_id") == job_id for it in items)

    # Cancel should work from PENDING.
    resp = client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    item = resp.json().get("item", {})
    assert item.get("state") == "cancelled"


def test_web_roots_api_and_wizard_job_path_resolution(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AUDIOMASON_FILE_IO_ROOTS_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("AUDIOMASON_FILE_IO_ROOTS_STAGE_DIR", str(tmp_path / "stage"))
    monkeypatch.setenv("AUDIOMASON_FILE_IO_ROOTS_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("AUDIOMASON_FILE_IO_ROOTS_OUTBOX_DIR", str(tmp_path / "outbox"))

    web_interface_plugin_cls = _get_web_interface_plugin_cls()
    app = web_interface_plugin_cls().create_app()
    client = _make_client(app)

    resp = client.get("/api/roots")
    assert resp.status_code == 200
    ids = [it.get("id") for it in resp.json().get("items", [])]
    assert "inbox" in ids
    assert "stage" in ids
    assert "outbox" in ids
