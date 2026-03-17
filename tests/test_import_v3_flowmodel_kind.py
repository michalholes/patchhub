"""Issue 105: FlowModel kind and v3 primitive metadata."""

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


PROMPT_V3_WITH_WRITES = {
    "version": 3,
    "entry_step_id": "ask_name",
    "nodes": [
        {
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {},
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
    "edges": [{"from": "ask_name", "to": "stop"}],
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


def test_get_flow_model_v3_declares_kind_and_primitive_metadata(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PROMPT_V3_WITH_WRITES
    )

    flow_model = engine.get_flow_model()

    assert flow_model["flowmodel_kind"] == "dsl_step_graph_v3"
    steps = {step["step_id"]: step for step in flow_model["steps"]}
    assert set(steps) == {"ask_name", "stop"}
    assert steps["ask_name"]["primitive_id"] == "ui.prompt_text"
    assert steps["ask_name"]["primitive_version"] == 1
    assert steps["ask_name"]["kind"] == "prompt"
    assert steps["ask_name"]["title"] == "ask_name"
    assert steps["stop"]["primitive_id"] == "ctrl.stop"
    assert steps["stop"]["kind"] == "step"

    state = engine.create_session("inbox", "")
    assert state["status"] == "in_progress"
    out = engine.submit_step(state["session_id"], "ask_name", {"value": "Ada"})
    assert out["status"] == "completed"
    assert out["answers"]["ask_name"]["value"] == "Ada"
    assert out["inputs"] == {}


PROMPT_V3_NO_WRITES = {
    "version": 3,
    "entry_step_id": "ask_name",
    "nodes": [
        {
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {},
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
    "edges": [{"from": "ask_name", "to": "stop"}],
}


def test_prompt_submit_without_writes_keeps_answers_and_inputs_empty(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PROMPT_V3_NO_WRITES
    )

    state = engine.create_session("inbox", "")
    assert state["status"] == "in_progress"

    out = engine.submit_step(state["session_id"], "ask_name", {"value": "Ada"})

    assert out["status"] == "completed"
    assert out["answers"] == {}
    assert out["inputs"] == {}
    assert [entry["result"] for entry in out["trace"]] == ["OK", "OK"]


PHASE2_FLOW = {
    "version": 3,
    "entry_step_id": "fork",
    "macros": {
        "fork_write": {
            "params": ["target_path"],
            "template": {
                "to_path": {"param_ref": "target_path"},
                "value": {"expr": "$.op.outputs.branch_order"},
            },
        }
    },
    "libraries": {
        "left_flow": {
            "entry_step_id": "left_set",
            "params": [],
            "nodes": [
                {
                    "step_id": "left_set",
                    "op": {
                        "primitive_id": "data.set",
                        "primitive_version": 1,
                        "inputs": {"value": "L"},
                        "writes": [
                            {
                                "to_path": "$.state.vars.left.value",
                                "value": {"expr": "$.op.outputs.value"},
                            }
                        ],
                    },
                },
                {
                    "step_id": "left_stop",
                    "op": {
                        "primitive_id": "ctrl.stop",
                        "primitive_version": 1,
                        "inputs": {},
                        "writes": [],
                    },
                },
            ],
            "edges": [{"from": "left_set", "to": "left_stop"}],
        }
    },
    "nodes": [
        {
            "step_id": "fork",
            "op": {
                "primitive_id": "parallel.fork_join",
                "primitive_version": 1,
                "inputs": {
                    "branch_order": ["left"],
                    "join_policy": "all",
                    "merge_mode": "fail_on_conflict",
                    "branches": {
                        "left": {
                            "target_library": "left_flow",
                            "target_subflow": "left_flow",
                            "param_bindings": [],
                        }
                    },
                },
                "writes": [
                    {
                        "macro_ref": "fork_write",
                        "args": {"target_path": "$.state.vars.fork.order"},
                    }
                ],
            },
        },
        {
            "step_id": "invoke",
            "op": {
                "primitive_id": "flow.invoke",
                "primitive_version": 1,
                "inputs": {
                    "target_library": "left_flow",
                    "target_subflow": "left_flow",
                    "param_bindings": [],
                },
                "writes": [],
            },
        },
        {
            "step_id": "loop",
            "op": {
                "primitive_id": "flow.loop",
                "primitive_version": 1,
                "inputs": {
                    "iterable_expr": {"expr": "$.state.vars.items"},
                    "item_var": "item",
                    "max_iterations": 3,
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
    "edges": [
        {"from": "fork", "to": "invoke"},
        {"from": "invoke", "to": "loop"},
        {"from": "loop", "to": "stop"},
    ],
}


def test_get_flow_model_v3_projects_phase2_capability_fields(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PHASE2_FLOW)

    flow_model = engine.get_flow_model()
    steps = {step["step_id"]: step for step in flow_model["steps"]}

    assert steps["fork"]["branch_order"] == ["left"]
    assert steps["fork"]["join_policy"] == "all"
    assert steps["fork"]["merge_mode"] == "fail_on_conflict"
    assert list(steps["fork"]["branches"]) == ["left"]

    assert steps["invoke"]["target_library"] == "left_flow"
    assert steps["invoke"]["target_subflow"] == "left_flow"
    assert steps["invoke"]["param_bindings"] == []

    assert steps["loop"]["item_var"] == "item"
    assert steps["loop"]["max_iterations"] == 3
    assert steps["loop"]["iterable_expr"] == {"expr": "$.state.vars.items"}

    assert flow_model["libraries"]["left_flow"]["entry_step_id"] == "left_set"
    assert flow_model["libraries"]["left_flow"]["steps"][0]["step_id"] == "left_set"
