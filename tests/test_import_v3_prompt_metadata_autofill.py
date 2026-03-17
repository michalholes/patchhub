"""Issue 108: prompt metadata autofill and PHASE 1 auto-advance."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


AUTOFILL_FLOW = {
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
                        "to_path": "$.state.vars.autofill_name",
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
                "inputs": {"value": True},
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
                    "prompt": "Enter the final name",
                    "default_expr": {"expr": "$.state.vars.autofill_name"},
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


def test_create_session_autofills_prompt_and_advances_without_submit(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, AUTOFILL_FLOW)

    state = engine.create_session("inbox", "")

    assert state["status"] == "completed"
    assert state["answers"]["ask_name"]["value"] == "Ada"
    assert state["current_step_id"] == "stop"
    assert state["completed_step_ids"] == ["ask_name"]
    assert [entry["step_id"] for entry in state["trace"]] == [
        "seed_name",
        "seed_flag",
        "ask_name",
        "stop",
    ]
