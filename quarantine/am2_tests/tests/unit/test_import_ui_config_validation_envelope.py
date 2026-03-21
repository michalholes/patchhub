"""UI /import/ui/config returns canonical error envelopes."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
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


def _make_engine(tmp_path: Path) -> ImportWizardEngine:
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
    return ImportWizardEngine(resolver=resolver)


@pytest.mark.skipif((not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required")
def test_set_config_invalid_body_returns_error_envelope(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)

    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    # Invalid: version must be int (normalize enforces type)
    resp = client.post("/import/ui/config", json={"config": {"version": "bad"}})

    assert resp.status_code == 400
    data = resp.json()
    assert isinstance(data, dict)
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
