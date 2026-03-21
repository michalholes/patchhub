"""Issue 117: end-to-end CLI acceptance for v3 Phase II capability smoke flows."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

run_launcher = import_module("plugins.import.cli_renderer").run_launcher
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH

PHASE2_ACCEPTANCE_PROGRAM = {
    "version": 3,
    "entry_step_id": "ask_name",
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
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {
                    "label": "Operator name",
                    "prompt": "Enter the operator name",
                    "default_value": "Michal",
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
                    },
                    {
                        "to_path": "$.state.vars.loop.last_index",
                        "value": {"expr": "$.op.outputs.iteration_index"},
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
    "edges": [
        {"from": "ask_name", "to": "invoke"},
        {"from": "invoke", "to": "fork"},
        {"from": "fork", "to": "seed_items"},
        {"from": "seed_items", "to": "loop"},
        {"from": "loop", "to": "stop"},
    ],
}


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, ConfigResolver, Path]:
    roots = {
        name: tmp_path / name for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
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
                    "render": {"confirm_defaults": True, "nav_ui": "prompt"},
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
    return ImportWizardEngine(resolver=resolver), resolver, roots["wizards"]


def _write_source_tree(tmp_path: Path) -> None:
    book_dir = tmp_path / "inbox" / "src" / "Author A" / "Book A"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "track01.mp3").write_text("x", encoding="utf-8")


def test_phase2_cli_acceptance_smoke_covers_runtime_capability_set(
    tmp_path: Path,
) -> None:
    _write_source_tree(tmp_path)
    engine, resolver, wizards_root = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs,
        RootName.WIZARDS,
        WIZARD_DEFINITION_REL_PATH,
        PHASE2_ACCEPTANCE_PROGRAM,
    )

    printed: list[str] = []
    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=lambda _prompt: "Operator",
        print_fn=printed.append,
    )

    assert rc == 0

    session_dirs = sorted((wizards_root / "import" / "sessions").iterdir())
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]

    effective_model = json.loads((session_dir / "effective_model.json").read_text(encoding="utf-8"))
    state = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))

    assert effective_model["flowmodel_kind"] == "dsl_step_graph_v3"
    assert state["status"] == "completed"
    assert state["answers"]["ask_name"]["value"] == "Operator"
    assert state["vars"]["called"]["name"] == "Ada"
    assert state["vars"]["invoke"]["target"] == "named_subflow"
    assert state["vars"]["fork"]["order"] == ["left", "right"]
    assert state["vars"]["left"]["value"] == "L"
    assert state["vars"]["right"]["value"] == "R"
    assert state["vars"]["loop"]["last_item"] == 3
    assert state["vars"]["loop"]["last_index"] == 2
    assert [entry["step_id"] for entry in state["trace"]] == [
        "ask_name",
        "lib_value",
        "lib_stop",
        "invoke",
        "left_value",
        "left_stop",
        "right_value",
        "right_stop",
        "fork",
        "seed_items",
        "loop",
        "loop",
        "loop",
        "loop",
        "stop",
    ]

    joined = "\n".join(printed)
    assert "Step: ask_name" in joined
    assert '"status": "completed"' in joined
