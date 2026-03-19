"""Strict validation tests for POST /import/ui/session/start."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
RootName = import_module("plugins.file_io.service").RootName
ensure_default_models = import_module("plugins.import.defaults").ensure_default_models
build_router = import_module("plugins.import.ui_api").build_router

_HAS_FASTAPI = True
try:
    import fastapi  # noqa: F401
except Exception:
    _HAS_FASTAPI = False

try:
    import httpx  # noqa: F401

    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False


def _make_engine(tmp_path: Path):
    roots = {
        "inbox": tmp_path / "inbox",
        "stage": tmp_path / "stage",
        "outbox": tmp_path / "outbox",
        "jobs": tmp_path / "jobs",
        "config": tmp_path / "config",
        "wizards": tmp_path / "wizards",
    }
    defaults = {
        "file_io": {
            "roots": {
                "inbox_dir": str(roots["inbox"]),
                "stage_dir": str(roots["stage"]),
                "outbox_dir": str(roots["outbox"]),
                "jobs_dir": str(roots["jobs"]),
                "config_dir": str(roots["config"]),
                "wizards_dir": str(roots["wizards"]),
            }
        },
        "output_dir": str(roots["outbox"]),
        "diagnostics": {"enabled": False},
    }
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver), roots


def _write_inbox_source_dir(roots: dict[str, Path], rel_dir: str) -> None:
    d = roots["inbox"] / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "file.txt").write_text("x", encoding="utf-8")


def _client_for_engine(tmp_path: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_source_dir(roots, "src")
    ensure_default_models(fs)

    app = FastAPI()
    app.include_router(build_router(engine=engine))
    return TestClient(app)


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_session_start_missing_mode_is_400(tmp_path: Path) -> None:
    client = _client_for_engine(tmp_path)

    resp = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src"},
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["details"][0]["path"] == "$.mode"


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_session_start_unknown_field_is_400(tmp_path: Path) -> None:
    client = _client_for_engine(tmp_path)

    resp = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src", "mode": "stage", "model": "x"},
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["details"][0]["path"] == "$.model"


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_session_start_invalid_mode_is_400(tmp_path: Path) -> None:
    client = _client_for_engine(tmp_path)

    resp = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src", "mode": "nope"},
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["details"][0]["path"] == "$.mode"


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_session_start_valid_payload_is_200(tmp_path: Path) -> None:
    client = _client_for_engine(tmp_path)

    resp = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src", "mode": "stage"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "session_id" in data


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_session_start_conflict_requires_explicit_intent(tmp_path: Path) -> None:
    client = _client_for_engine(tmp_path)

    first = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src", "mode": "stage"},
    )
    assert first.status_code == 200

    resp = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src", "mode": "stage"},
    )

    assert resp.status_code == 409
    data = resp.json()
    assert data["error"]["code"] == "SESSION_START_CONFLICT"
    meta = data["error"]["details"][0]["meta"]
    assert meta["session_id"] == first.json()["session_id"]


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_session_start_new_intent_resets_existing_session(tmp_path: Path) -> None:
    client = _client_for_engine(tmp_path)

    first = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src", "mode": "stage"},
    )
    assert first.status_code == 200
    session_id = first.json()["session_id"]

    resp = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src", "mode": "stage", "intent": "new"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert data["status"] == "in_progress"
