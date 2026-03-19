"""Tests for canonical error envelopes in import UI routes."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
RootName = import_module("plugins.file_io.service").RootName
ensure_default_models = import_module("plugins.import.defaults").ensure_default_models
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
read_json = import_module("plugins.import.storage").read_json
build_router = import_module("plugins.import.ui_api").build_router
import_cli_main = import_module("plugins.import.cli").import_cli_main

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


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_session_start_returns_invariant_violation_envelope(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_source_dir(roots, "src")

    ensure_default_models(fs)
    flow_config = read_json(fs, RootName.WIZARDS, "import/config/flow_config.json")
    assert isinstance(flow_config, dict)

    flow_config["steps"] = {"select_authors": {"enabled": False}}
    atomic_write_json(
        fs, RootName.WIZARDS, "import/config/flow_config.json", flow_config
    )

    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    resp = client.post(
        "/import/ui/session/start",
        json={"root": "inbox", "path": "src", "mode": "stage"},
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "INVARIANT_VIOLATION"


def test_cli_missing_model_envelope_references_wizard_definition_and_flow_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = _make_engine(tmp_path)
    resolver = engine._resolver

    def _boom(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("import/definitions/wizard_definition.json")

    monkeypatch.setattr(
        import_module("plugins.import.cli"), "start_user_facing_session", _boom
    )

    with pytest.raises(SystemExit) as exc:
        import_cli_main(
            ["wizard", "start", "--root", "inbox", "--path", "src"],
            engine=engine,
            resolver=resolver,
        )

    assert exc.value.code == 1
    out = capsys.readouterr().out
    data = __import__("json").loads(out)
    assert data["code"] == "missing_wizard_model"
    assert data["details"]["expected_rel_paths"] == [
        "import/definitions/wizard_definition.json",
        "import/config/flow_config.json",
    ]
