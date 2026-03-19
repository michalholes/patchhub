"""Issue 102: WizardDefinition v3 lifecycle and authored artifact failures."""

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


def _minimal_v3_definition() -> dict[str, object]:
    return {
        "version": 3,
        "entry_step_id": "pick_author",
        "nodes": [
            {
                "step_id": "pick_author",
                "op": {
                    "primitive_id": "ui.prompt_select",
                    "primitive_version": 1,
                    "inputs": {},
                    "writes": [],
                },
            }
        ],
        "edges": [],
    }


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_wizard_definition_v3_draft_activate_history_and_rollback(
    tmp_path: Path,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    active0 = client.get("/import/ui/wizard-definition").json()["definition"]
    assert active0["version"] == 3
    assert active0["entry_step_id"] == "select_authors"

    wd = _minimal_v3_definition()
    post = client.post("/import/ui/wizard-definition", json={"definition": wd})
    assert post.status_code == 200
    assert post.json()["definition"]["version"] == 3

    activate = client.post("/import/ui/wizard-definition/activate", json={})
    assert activate.status_code == 200
    assert activate.json()["definition"]["version"] == 3

    active1 = client.get("/import/ui/wizard-definition").json()["definition"]
    assert active1["version"] == 3
    assert active1["entry_step_id"] == "pick_author"

    history = client.get("/import/ui/wizard-definition/history")
    assert history.status_code == 200
    items = history.json()["items"]
    assert items

    rollback = client.post(
        "/import/ui/wizard-definition/rollback", json={"id": str(items[0]["id"])}
    )
    assert rollback.status_code == 200
    rolled = rollback.json()["definition"]
    assert rolled["version"] == 3
    assert rolled["entry_step_id"] == active0["entry_step_id"]

    active2 = client.get("/import/ui/wizard-definition").json()["definition"]
    assert active2 == active0


def test_load_or_bootstrap_rejects_invalid_v3_with_visible_error(
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
            "entry_step_id": "Bad.Step",
            "nodes": [
                {
                    "step_id": "Bad.Step",
                    "op": {
                        "primitive_id": "ui.prompt_select",
                        "primitive_version": 1,
                        "inputs": {},
                        "writes": [],
                    },
                }
            ],
            "edges": [],
        },
    )

    with pytest.raises(Exception) as exc_info:
        load_or_bootstrap_wizard_definition(fs)

    message = str(exc_info.value)
    assert "wizard_definition runtime artifact is invalid" in message
    assert "wizard_definition.json" in message


def test_create_session_surfaces_hint_when_authored_definition_is_invalid(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()

    atomic_write_json(
        fs,
        RootName.WIZARDS,
        WIZARD_DEFINITION_REL_PATH,
        {"version": 3, "entry_step_id": "Bad.Step", "nodes": [], "edges": []},
    )

    result = engine.create_session("inbox", "")

    assert result["error"]["code"] == "VALIDATION_ERROR"
    detail = result["error"]["details"][0]
    assert detail["reason"] == "invalid_authored_wizard_definition"
    assert (
        detail["meta"]["artifact_path"]
        == "wizards/import/definitions/wizard_definition.json"
    )
    assert "Fix or replace" in detail["meta"]["hint"]
