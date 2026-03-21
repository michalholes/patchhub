"""Issue 102: WizardDefinition v3 unknown primitive endpoint validation."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
build_router = import_module("plugins.import.ui_api").build_router
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
load_or_bootstrap_wizard_definition = import_module(
    "plugins.import.wizard_definition_model"
).load_or_bootstrap_wizard_definition
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH

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
def test_post_wizard_definition_rejects_unknown_primitive(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    wd = {
        "version": 3,
        "entry_step_id": "select_authors",
        "nodes": [
            {
                "step_id": "select_authors",
                "op": {
                    "primitive_id": "__unknown__",
                    "primitive_version": 999,
                    "inputs": {},
                    "writes": [],
                },
            }
        ],
        "edges": [],
    }

    response = client.post("/import/ui/wizard-definition", json={"definition": wd})

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["details"][0]["reason"] == "unknown_primitive"


def test_load_or_bootstrap_rejects_unknown_v3_primitive_with_visible_error(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()

    atomic_write_json(
        fs,
        RootName.WIZARDS,
        WIZARD_DEFINITION_REL_PATH,
        {
            "version": 3,
            "entry_step_id": "bad_step",
            "nodes": [
                {
                    "step_id": "bad_step",
                    "op": {
                        "primitive_id": "ui.prompt_missing",
                        "primitive_version": 1,
                        "inputs": {},
                        "writes": [],
                    },
                }
            ],
            "edges": [],
        },
    )

    with pytest.raises(Exception) as excinfo:
        load_or_bootstrap_wizard_definition(fs, bootstrap_default_version=3)

    assert "wizard_definition runtime artifact is invalid" in str(excinfo.value)
    assert "fix or replace wizards/import/definitions/wizard_definition.json" in str(excinfo.value)
