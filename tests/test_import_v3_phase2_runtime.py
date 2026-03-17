"""Issue 115: Phase II runtime coverage for the import DSL."""

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


FLOW_INVOKE_PROGRAM = {
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
        }
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
            "step_id": "stop",
            "op": {
                "primitive_id": "ctrl.stop",
                "primitive_version": 1,
                "inputs": {},
                "writes": [],
            },
        },
    ],
    "edges": [{"from": "invoke", "to": "stop"}],
}


FORK_JOIN_PROGRAM = {
    "version": 3,
    "entry_step_id": "fork",
    "libraries": {
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
            "step_id": "stop",
            "op": {
                "primitive_id": "ctrl.stop",
                "primitive_version": 1,
                "inputs": {},
                "writes": [],
            },
        },
    ],
    "edges": [{"from": "fork", "to": "stop"}],
}


LOOP_PROGRAM = {
    "version": 3,
    "entry_step_id": "loop",
    "nodes": [
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
                    },
                    {
                        "to_path": "$.state.vars.loop.last_index",
                        "value": {"expr": "$.op.outputs.iteration_index"},
                    },
                    {
                        "to_path": "$.state.answers.loop.value",
                        "value": {"expr": "$.inputs.item"},
                    },
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
    "edges": [{"from": "loop", "to": "stop"}],
}


LOOP_GUARD_PROGRAM = {
    **LOOP_PROGRAM,
    "nodes": [
        {
            **LOOP_PROGRAM["nodes"][0],
            "op": {
                **LOOP_PROGRAM["nodes"][0]["op"],
                "inputs": {
                    "iterable_expr": {"expr": "$.state.vars.items"},
                    "item_var": "item",
                    "max_iterations": 2,
                },
            },
        },
        LOOP_PROGRAM["nodes"][1],
    ],
}


SEED_ITEMS_PROGRAM = {
    "version": 3,
    "entry_step_id": "seed_items",
    "nodes": [
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
        *LOOP_PROGRAM["nodes"],
    ],
    "edges": [
        {"from": "seed_items", "to": "loop"},
        {"from": "loop", "to": "stop"},
    ],
}


SEED_ITEMS_GUARD_PROGRAM = {
    **SEED_ITEMS_PROGRAM,
    "nodes": [SEED_ITEMS_PROGRAM["nodes"][0], *LOOP_GUARD_PROGRAM["nodes"]],
}


def _make_engine(tmp_path: Path) -> ImportWizardEngine:
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
    }
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver)


def test_flow_invoke_uses_explicit_param_binding_and_deterministic_trace(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, FLOW_INVOKE_PROGRAM
    )

    state = engine.create_session("inbox", "")

    assert state["status"] == "completed"
    assert state["vars"]["called"]["name"] == "Ada"
    assert state["vars"]["invoke"]["target"] == "named_subflow"
    assert state["vars"]["subflows"]["invoke"]["param_bindings"] == {"name": "Ada"}
    assert [entry["step_id"] for entry in state["trace"]] == [
        "lib_value",
        "lib_stop",
        "invoke",
        "stop",
    ]


def test_fork_join_preserves_branch_order_and_trace_order(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, FORK_JOIN_PROGRAM
    )

    state = engine.create_session("inbox", "")

    assert state["status"] == "completed"
    assert state["vars"]["left"]["value"] == "L"
    assert state["vars"]["right"]["value"] == "R"
    assert state["vars"]["fork"]["order"] == ["left", "right"]
    assert state["vars"]["branches"]["fork"]["branch_order"] == ["left", "right"]
    assert [entry["step_id"] for entry in state["trace"]] == [
        "left_value",
        "left_stop",
        "right_value",
        "right_stop",
        "fork",
        "stop",
    ]


def test_loop_emits_deterministic_iteration_trace_order(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, SEED_ITEMS_PROGRAM
    )

    state = engine.create_session("inbox", "")

    assert state["status"] == "completed"
    assert state["vars"]["loop"]["last_item"] == 3
    assert state["vars"]["loop"]["last_index"] == 2
    assert state["answers"]["loop"]["value"] == 3
    assert [entry.get("iteration_index") for entry in state["trace"][1:4]] == [0, 1, 2]
    assert [entry["step_id"] for entry in state["trace"]] == [
        "seed_items",
        "loop",
        "loop",
        "loop",
        "loop",
        "stop",
    ]


def test_loop_guard_fails_when_iterable_exceeds_max_iterations(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, SEED_ITEMS_GUARD_PROGRAM
    )

    out = engine.create_session("inbox", "")

    assert out["error"]["code"] == "INVARIANT_VIOLATION"
    assert out["error"]["message"] == "loop_max_iterations_exceeded"
