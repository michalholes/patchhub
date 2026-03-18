"""Issue 117: Phase II editor activation applies only to the next import run."""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
read_json = import_module("plugins.import.storage").read_json
wizard_storage = import_module("plugins.import.wizard_editor_storage")
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH

PHASE2_EDITOR_PROGRAM = {
    "version": 3,
    "entry_step_id": "invoke",
    "libraries": {
        "named_subflow": {
            "entry_step_id": "lib_value",
            "params": [{"name": "name", "required": True}],
            "nodes": [
                {
                    "step_id": "lib_value",
                    "op": {
                        "primitive_id": "data.set",
                        "primitive_version": 1,
                        "inputs": {"value": {"expr": "$.inputs.name"}},
                        "writes": [
                            {
                                "to_path": "$.state.vars.called.name",
                                "value": {"expr": "$.op.outputs.value"},
                            }
                        ],
                    },
                },
                {
                    "step_id": "lib_stop",
                    "op": {
                        "primitive_id": "ctrl.stop",
                        "primitive_version": 1,
                        "inputs": {},
                        "writes": [],
                    },
                },
            ],
            "edges": [{"from": "lib_value", "to": "lib_stop"}],
        },
        "left_flow": {
            "entry_step_id": "left_value",
            "params": [],
            "nodes": [
                {
                    "step_id": "left_value",
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
            "edges": [{"from": "left_value", "to": "left_stop"}],
        },
        "right_flow": {
            "entry_step_id": "right_value",
            "params": [],
            "nodes": [
                {
                    "step_id": "right_value",
                    "op": {
                        "primitive_id": "data.set",
                        "primitive_version": 1,
                        "inputs": {"value": "R"},
                        "writes": [
                            {
                                "to_path": "$.state.vars.right.value",
                                "value": {"expr": "$.op.outputs.value"},
                            }
                        ],
                    },
                },
                {
                    "step_id": "right_stop",
                    "op": {
                        "primitive_id": "ctrl.stop",
                        "primitive_version": 1,
                        "inputs": {},
                        "writes": [],
                    },
                },
            ],
            "edges": [{"from": "right_value", "to": "right_stop"}],
        },
    },
    "nodes": [
        {
            "step_id": "invoke",
            "op": {
                "primitive_id": "flow.invoke",
                "primitive_version": 1,
                "inputs": {
                    "target_library": "named_subflow",
                    "target_subflow": "named_subflow",
                    "param_bindings": [{"name": "name", "value": "Ada"}],
                },
                "writes": [
                    {
                        "to_path": "$.state.vars.invoke.target",
                        "value": {"expr": "$.op.outputs.target_library"},
                    }
                ],
            },
        },
        {
            "step_id": "fork",
            "op": {
                "primitive_id": "parallel.fork_join",
                "primitive_version": 1,
                "inputs": {
                    "branch_order": ["left", "right"],
                    "join_policy": "all",
                    "merge_mode": "fail_on_conflict",
                    "branches": {
                        "left": {
                            "target_library": "left_flow",
                            "target_subflow": "left_flow",
                            "param_bindings": [],
                        },
                        "right": {
                            "target_library": "right_flow",
                            "target_subflow": "right_flow",
                            "param_bindings": [],
                        },
                    },
                },
                "writes": [
                    {
                        "to_path": "$.state.vars.fork.order",
                        "value": {"expr": "$.op.outputs.branch_order"},
                    }
                ],
            },
        },
        {
            "step_id": "seed_items",
            "op": {
                "primitive_id": "data.set",
                "primitive_version": 1,
                "inputs": {"value": [1, 2, 3]},
                "writes": [
                    {
                        "to_path": "$.state.vars.items",
                        "value": {"expr": "$.op.outputs.value"},
                    }
                ],
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
                "writes": [
                    {
                        "to_path": "$.state.vars.loop.last_item",
                        "value": {"expr": "$.op.outputs.item"},
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
        {"from": "invoke", "to": "fork"},
        {"from": "fork", "to": "seed_items"},
        {"from": "seed_items", "to": "loop"},
        {"from": "loop", "to": "stop"},
    ],
}


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, dict[str, Path]]:
    roots = {
        name: tmp_path / name
        for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
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
        "plugins": {
            "import": {
                "cli": {
                    "launcher_mode": "fixed",
                    "default_root": "inbox",
                    "default_path": "src",
                    "noninteractive": False,
                    "render": {"nav_ui": "prompt"},
                }
            }
        },
    }
    resolver = ConfigResolver(
        cli_args={},
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver), roots


def _write_source_tree(roots: dict[str, Path]) -> None:
    book_dir = roots["inbox"] / "src" / "Author A" / "Book A"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "track01.mp3").write_text("x", encoding="utf-8")


def _flow_step(state: dict[str, object], step_id: str) -> dict[str, object]:
    effective_model = state["effective_model"]
    assert isinstance(effective_model, dict)
    steps = effective_model.get("steps")
    assert isinstance(steps, list)
    for step in steps:
        if isinstance(step, dict) and step.get("step_id") == step_id:
            return step
    raise AssertionError(f"step not found: {step_id}")


def _workflow_node(workflow: dict[str, object], step_id: str) -> dict[str, object]:
    nodes = workflow.get("nodes")
    assert isinstance(nodes, list)
    for node in nodes:
        if isinstance(node, dict) and node.get("step_id") == step_id:
            return node
    raise AssertionError(f"missing workflow step: {step_id}")


def test_phase2_editor_activation_affects_only_the_next_import_run(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_source_tree(roots)
    fs = engine.get_file_service()
    atomic_write_json(
        fs,
        RootName.WIZARDS,
        WIZARD_DEFINITION_REL_PATH,
        PHASE2_EDITOR_PROGRAM,
    )

    state1 = engine.create_session("inbox", "src")
    session_id_1 = str(state1["session_id"])
    loaded1 = engine.get_state(session_id_1)

    assert loaded1["vars"]["called"]["name"] == "Ada"
    assert loaded1["vars"]["fork"]["order"] == ["left", "right"]
    assert _flow_step(loaded1, "loop")["inputs"]["max_iterations"] == 3

    draft = deepcopy(wizard_storage.get_wizard_definition_draft(fs))
    assert draft["version"] == 3

    for node in draft["nodes"]:
        if node.get("step_id") == "invoke":
            node["op"]["inputs"]["param_bindings"] = [
                {"name": "name", "value": "Grace"}
            ]
        elif node.get("step_id") == "fork":
            node["op"]["inputs"]["branch_order"] = ["right", "left"]
        elif node.get("step_id") == "loop":
            node["op"]["inputs"]["max_iterations"] = 5

    wizard_storage.put_wizard_definition_draft(fs, draft)
    wizard_storage.activate_wizard_definition_draft(fs)

    state2 = engine.create_session("inbox", "src")
    session_id_2 = str(state2["session_id"])
    loaded2 = engine.get_state(session_id_2)

    workflow1 = read_json(
        fs,
        RootName.WIZARDS,
        f"import/sessions/{session_id_1}/effective_workflow.json",
    )
    workflow2 = read_json(
        fs,
        RootName.WIZARDS,
        f"import/sessions/{session_id_2}/effective_workflow.json",
    )

    assert session_id_2 != session_id_1
    assert _workflow_node(workflow1, "invoke")["op"]["inputs"]["param_bindings"] == [
        {"name": "name", "value": "Ada"}
    ]
    assert _workflow_node(workflow2, "invoke")["op"]["inputs"]["param_bindings"] == [
        {"name": "name", "value": "Grace"}
    ]
    assert loaded2["vars"]["called"]["name"] == "Grace"
    assert loaded2["vars"]["fork"]["order"] == ["right", "left"]
    assert _flow_step(loaded2, "loop")["inputs"]["max_iterations"] == 5

    loaded1_again = engine.get_state(session_id_1)
    assert loaded1_again["vars"]["called"]["name"] == "Ada"
    assert loaded1_again["vars"]["fork"]["order"] == ["left", "right"]
    assert _flow_step(loaded1_again, "loop")["inputs"]["max_iterations"] == 3
