"""Issue 108: FlowModel prompt metadata projection and step API normalization."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

FinalizeError = import_module("plugins.import.errors").FinalizeError
build_step_catalog_projection = import_module(
    "plugins.import.step_catalog"
).build_step_catalog_projection

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
build_router = import_module("plugins.import.ui_api").build_router
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH
validate_flow_config_editor_boundary = import_module(
    "plugins.import.flow_config_validation"
).validate_flow_config_editor_boundary
validate_wizard_definition_structure = import_module(
    "plugins.import.wizard_definition_model"
).validate_wizard_definition_structure
step_catalog_module = import_module("plugins.import.step_catalog")


PROMPT_METADATA_FLOW = {
    "version": 3,
    "entry_step_id": "seed_name",
    "nodes": [
        {
            "step_id": "seed_name",
            "op": {
                "primitive_id": "data.set",
                "primitive_version": 1,
                "inputs": {"value": "Ada"},
                "writes": [
                    {
                        "to_path": "$.state.vars.seed_name",
                        "value": {"expr": "$.op.outputs.value"},
                    }
                ],
            },
        },
        {
            "step_id": "seed_flag",
            "op": {
                "primitive_id": "data.set",
                "primitive_version": 1,
                "inputs": {"value": False},
                "writes": [
                    {
                        "to_path": "$.state.vars.should_autofill",
                        "value": {"expr": "$.op.outputs.value"},
                    }
                ],
            },
        },
        {
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {
                    "label": "Name",
                    "prompt": "Enter the normalized name",
                    "help": "Used by the renderer",
                    "default_value": "fallback",
                    "prefill": "literal",
                    "default_expr": {"expr": "$.state.vars.seed_name"},
                    "prefill_expr": {"expr": "$.state.vars.seed_name"},
                    "autofill_if": {"expr": "$.state.vars.should_autofill"},
                },
                "writes": [
                    {
                        "to_path": "$.state.answers.ask_name.value",
                        "value": {"expr": "$.op.outputs.value"},
                    }
                ],
            },
        },
        {
            "step_id": "stop",
            "op": {
                "primitive_id": "ctrl.stop",
                "primitive_version": 1,
                "inputs": {},
                "writes": [],
            },
        },
    ],
    "edges": [
        {"from": "seed_name", "to": "seed_flag"},
        {"from": "seed_flag", "to": "ask_name"},
        {"from": "ask_name", "to": "stop"},
    ],
}


def _make_engine(tmp_path: Path) -> ImportWizardEngine:
    roots = {
        "inbox": tmp_path / "inbox",
        "stage": tmp_path / "stage",
        "outbox": tmp_path / "outbox",
        "jobs": tmp_path / "jobs",
        "config": tmp_path / "config",
        "wizards": tmp_path / "wizards",
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
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


def test_flow_model_projects_prompt_ui_and_step_api_normalizes_current_step(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PROMPT_METADATA_FLOW
    )

    flow_model = engine.get_flow_model()
    steps = {step["step_id"]: step for step in flow_model["steps"]}

    assert steps["ask_name"]["ui"] == {
        "label": "Name",
        "prompt": "Enter the normalized name",
        "help": "Used by the renderer",
        "default_value": "fallback",
        "prefill": "literal",
        "default_expr": {"expr": "$.state.vars.seed_name"},
        "prefill_expr": {"expr": "$.state.vars.seed_name"},
        "autofill_if": {"expr": "$.state.vars.should_autofill"},
    }
    assert "ui" not in steps["seed_name"]
    assert "ui" not in steps["stop"]

    state = engine.create_session("inbox", "")
    assert state["status"] == "in_progress"
    assert state["current_step_id"] == "ask_name"

    step = engine.get_step_definition(state["session_id"], "ask_name")

    assert step["ui"] == {
        "label": "Name",
        "prompt": "Enter the normalized name",
        "help": "Used by the renderer",
        "default_value": "Ada",
        "prefill": "Ada",
        "autofill_if": False,
    }


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


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_step_routes_project_active_v3_metadata(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PROMPT_METADATA_FLOW
    )

    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    index = client.get("/import/ui/steps-index")
    assert index.status_code == 200
    items = {item["step_id"]: item for item in index.json()["items"]}
    assert "ask_name" in items
    assert "parallelism" not in items
    assert items["ask_name"]["displayName"] == "Name"

    missing = client.get("/import/ui/steps/parallelism")
    assert missing.status_code == 404

    detail = client.get("/import/ui/steps/ask_name")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["title"] == "Name"
    assert payload["displayName"] == "Name"
    assert payload["description"] == "Enter the normalized name"
    assert payload["kind"] == "optional"
    assert payload["pinned"] is False
    field_keys = [field["key"] for field in payload["settings_schema"]["fields"]]
    assert "label" in field_keys
    assert "default_expr" in field_keys
    assert payload["defaults_template"]["default_value"] == "fallback"


def test_build_step_catalog_projection_uses_only_active_authority() -> None:
    projection = build_step_catalog_projection(
        wizard_definition=PROMPT_METADATA_FLOW,
        flow_config={"version": 1, "steps": {}, "defaults": {}},
    )

    assert set(projection) == {"seed_name", "seed_flag", "ask_name", "stop"}
    assert "parallelism" not in projection
    assert projection["ask_name"]["displayName"] == "Name"


def test_build_step_catalog_projection_rejects_underivable_inputs() -> None:
    with pytest.raises(FinalizeError, match="wizard_definition must be version 2 or 3"):
        build_step_catalog_projection(
            wizard_definition={"version": 99},
            flow_config={"version": 1, "steps": {}, "defaults": {}},
        )

    with pytest.raises(
        FinalizeError, match="wizard_definition graph.nodes must be a list"
    ):
        build_step_catalog_projection(
            wizard_definition={"version": 2, "graph": {}},
            flow_config={"version": 1, "steps": {}, "defaults": {}},
        )


def test_flow_config_editor_boundary_preserves_defaults_without_catalog_authority() -> (
    None
):
    original = step_catalog_module.STEP_CATALOG.get("parallelism")
    step_catalog_module.STEP_CATALOG["parallelism"] = {"id": "parallelism"}
    try:
        out = validate_flow_config_editor_boundary(
            {
                "version": 1,
                "steps": {},
                "defaults": {"parallelism": {"workers": 4, "custom": {"mode": "x"}}},
            }
        )
    finally:
        if original is None:
            step_catalog_module.STEP_CATALOG.pop("parallelism", None)
        else:
            step_catalog_module.STEP_CATALOG["parallelism"] = original

    assert out["defaults"] == {"parallelism": {"workers": 4, "custom": {"mode": "x"}}}


def test_validate_wizard_definition_structure_does_not_read_projection_behavioral_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = step_catalog_module.STEP_CATALOG.get("select_authors")
    step_catalog_module.STEP_CATALOG["select_authors"] = {"id": "select_authors"}

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("projection helper should not be consulted")

    monkeypatch.setattr(step_catalog_module, "get_step_details", _boom)
    monkeypatch.setattr(
        step_catalog_module, "build_default_step_catalog_projection", _boom
    )

    try:
        validate_wizard_definition_structure(
            {
                "version": 2,
                "graph": {
                    "entry_step_id": "select_authors",
                    "nodes": [
                        {"step_id": "select_authors"},
                        {"step_id": "select_books"},
                        {"step_id": "plan_preview_batch"},
                        {"step_id": "conflict_policy"},
                        {"step_id": "final_summary_confirm"},
                        {"step_id": "processing"},
                    ],
                    "edges": [
                        {
                            "from_step_id": "select_authors",
                            "to_step_id": "select_books",
                            "priority": 0,
                            "when": None,
                        },
                        {
                            "from_step_id": "select_books",
                            "to_step_id": "plan_preview_batch",
                            "priority": 0,
                            "when": None,
                        },
                        {
                            "from_step_id": "plan_preview_batch",
                            "to_step_id": "conflict_policy",
                            "priority": 0,
                            "when": None,
                        },
                        {
                            "from_step_id": "conflict_policy",
                            "to_step_id": "final_summary_confirm",
                            "priority": 0,
                            "when": None,
                        },
                        {
                            "from_step_id": "final_summary_confirm",
                            "to_step_id": "processing",
                            "priority": 0,
                            "when": None,
                        },
                    ],
                },
            }
        )
    finally:
        if original is None:
            step_catalog_module.STEP_CATALOG.pop("select_authors", None)
        else:
            step_catalog_module.STEP_CATALOG["select_authors"] = original
