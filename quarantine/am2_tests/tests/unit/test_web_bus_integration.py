from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


def _get_web_interface_plugin_cls() -> type:
    repo_root = Path(__file__).resolve().parents[2]
    repo_root_s = str(repo_root)
    if repo_root_s not in sys.path:
        sys.path.insert(0, repo_root_s)

    from plugins.web_interface.core import WebInterfacePlugin

    return WebInterfacePlugin


def _make_client(app: Any) -> Any:
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_web_emits_route_boundary_diagnostics(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    from audiomason.core.events import get_event_bus

    bus = get_event_bus()
    bus.clear()

    events: list[tuple[str, dict[str, Any]]] = []

    def on_start(data: dict[str, Any]) -> None:
        events.append(("start", data))

    def on_end(data: dict[str, Any]) -> None:
        events.append(("end", data))

    bus.subscribe("boundary.start", on_start)
    bus.subscribe("boundary.end", on_end)

    web_cls = _get_web_interface_plugin_cls()
    app = web_cls().create_app(verbosity=3)
    client = _make_client(app)

    resp = client.get("/api/health?x=1")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    starts = [d for (t, d) in events if t == "start"]
    ends = [d for (t, d) in events if t == "end"]

    assert starts, "expected at least one boundary.start event"
    assert ends, "expected at least one boundary.end event"

    s0 = starts[0]
    assert s0.get("event") == "boundary.start"
    assert s0.get("component") == "web_interface"
    assert "operation" in s0
    assert isinstance(s0.get("data"), dict)

    e0 = ends[0]
    assert e0.get("event") == "boundary.end"
    assert e0.get("component") == "web_interface"
    assert e0.get("data", {}).get("status") == "succeeded"

    # debug verbosity includes query params (best-effort)
    assert s0.get("data", {}).get("query", {}).get("x") == "1"

    bus.unsubscribe("boundary.start", on_start)
    bus.unsubscribe("boundary.end", on_end)


def test_web_has_no_import_pause_resume_endpoints(tmp_path: Path, monkeypatch: Any) -> None:
    # Minimal File IO roots so ImportEngineService can initialize.
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    monkeypatch.setenv("AUDIOMASON_FILE_IO_ROOTS_INBOX_DIR", str(inbox))
    monkeypatch.setenv("HOME", str(tmp_path))

    from audiomason.core.events import get_event_bus

    bus = get_event_bus()
    bus.clear()

    seen: list[str] = []

    def on_pause(data: dict[str, Any]) -> None:
        seen.append("pause:" + str(data.get("data", {}).get("status")))

    def on_resume(data: dict[str, Any]) -> None:
        seen.append("resume:" + str(data.get("data", {}).get("status")))

    bus.subscribe("import.pause", on_pause)
    bus.subscribe("import.resume", on_resume)

    web_cls = _get_web_interface_plugin_cls()
    app = web_cls().create_app()
    client = _make_client(app)

    resp = client.post("/api/import_wizard/pause_queue")
    assert resp.status_code == 404
    resp = client.post("/api/import_wizard/resume_queue")
    assert resp.status_code == 404

    assert not seen

    bus.unsubscribe("import.pause", on_pause)
    bus.unsubscribe("import.resume", on_resume)
