"""Issue 108: prompt metadata validation and ui.message behavior."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH
FinalizeError = import_module("plugins.import.errors").FinalizeError


MESSAGE_FLOW = {
    "version": 3,
    "entry_step_id": "message",
    "nodes": [
        {
            "step_id": "message",
            "op": {
                "primitive_id": "ui.message",
                "primitive_version": 1,
                "inputs": {
                    "prompt": "ignored",
                    "default_value": "ignored",
                    "autofill_if": {"expr": "$.state.vars.flag"},
                },
                "writes": [],
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
    "edges": [{"from": "message", "to": "stop"}],
}


INVALID_AUTOFILL_FLOW = {
    "version": 3,
    "entry_step_id": "ask_name",
    "nodes": [
        {
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {
                    "prompt": "Name",
                    "autofill_if": True,
                },
                "writes": [],
            },
        }
    ],
    "edges": [],
}


NON_BOOL_AUTOFILL_FLOW = {
    "version": 3,
    "entry_step_id": "seed_flag",
    "nodes": [
        {
            "step_id": "seed_flag",
            "op": {
                "primitive_id": "data.set",
                "primitive_version": 1,
                "inputs": {"value": "yes"},
                "writes": [
                    {
                        "to_path": "$.state.vars.flag",
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
                    "prompt": "Name",
                    "default_value": "Ada",
                    "autofill_if": {"expr": "$.state.vars.flag"},
                },
                "writes": [],
            },
        },
    ],
    "edges": [{"from": "seed_flag", "to": "ask_name"}],
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


def test_ui_message_does_not_project_prompt_metadata(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, MESSAGE_FLOW)

    flow_model = engine.get_flow_model()
    steps = {step["step_id"]: step for step in flow_model["steps"]}

    assert "ui" not in steps["message"]

    state = engine.create_session("inbox", "")
    assert state["status"] == "completed"
    assert [entry["step_id"] for entry in state["trace"]] == ["message", "stop"]


def test_invalid_autofill_metadata_requires_expr_ref(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, INVALID_AUTOFILL_FLOW)

    with pytest.raises(FinalizeError, match="autofill_if must be ExprRef"):
        engine.get_flow_model()


def test_non_bool_autofill_expr_fails_during_phase1(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, NON_BOOL_AUTOFILL_FLOW)

    out = engine.create_session("inbox", "")

    assert out["error"]["code"] == "INVARIANT_VIOLATION"
    assert "autofill_if must resolve to bool" in out["error"]["message"]
