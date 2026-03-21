"""Issue 116: Phase II visual authoring for v3 editor capabilities."""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_import_ui_editor_v3_prompt_form import (
    _collect_attr_values,
    _run_graph_ops,
    _run_library_panel,
    _run_node_form,
    _run_palette,
)
from tests.test_import_ui_editor_v3_raw_json_roundtrip import (
    _RAW_JSON_SCRIPT,
    _run_node,
)

PHASE2_DEFINITION = {
    "version": 3,
    "entry_step_id": "invoke_root",
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
        "named_subflow": {
            "entry_step_id": "lib_prompt",
            "params": [{"name": "name", "required": True}],
            "nodes": [
                {
                    "step_id": "lib_prompt",
                    "op": {
                        "primitive_id": "ui.prompt_text",
                        "primitive_version": 1,
                        "inputs": {"label": "Name", "raw_only": {"nested": [1, 2]}},
                        "writes": [],
                    },
                }
            ],
            "edges": [],
        },
        "other_subflow": {
            "entry_step_id": "other_stop",
            "params": [{"name": "code", "required": False}],
            "nodes": [
                {
                    "step_id": "other_stop",
                    "op": {
                        "primitive_id": "ctrl.stop",
                        "primitive_version": 1,
                        "inputs": {},
                        "writes": [],
                    },
                }
            ],
            "edges": [],
        },
    },
    "nodes": [
        {
            "step_id": "invoke_root",
            "op": {
                "primitive_id": "flow.invoke",
                "primitive_version": 1,
                "inputs": {
                    "target_library": "named_subflow",
                    "target_subflow": "named_subflow",
                    "param_bindings": [{"name": "name", "value": "Ada"}],
                },
                "writes": [],
            },
        },
        {
            "step_id": "fork_root",
            "op": {
                "primitive_id": "parallel.fork_join",
                "primitive_version": 1,
                "inputs": {
                    "branch_order": ["left"],
                    "join_policy": "all",
                    "merge_mode": "fail_on_conflict",
                    "branches": {
                        "left": {
                            "target_library": "named_subflow",
                            "target_subflow": "named_subflow",
                            "param_bindings": [{"name": "name", "value": "Ada"}],
                        }
                    },
                },
                "writes": [{"macro_ref": "fork_write", "args": {"target_path": "$.state"}}],
            },
        },
        {
            "step_id": "loop_root",
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
    ],
    "edges": [],
}


def test_index_loads_phase2_assets_before_boot() -> None:
    source = Path("plugins/import/ui/web/index.html").read_text(encoding="utf-8")
    assert source.index("dsl_editor/library_panel.js") < source.index("dsl_editor/boot_v3.js")
    assert source.index("dsl_editor/capability_forms.js") < source.index("dsl_editor/boot_v3.js")


def test_palette_exposes_phase2_add_node_affordances() -> None:
    values = _run_palette(
        {
            "registry": [
                {
                    "primitive_id": "parallel.fork_join",
                    "version": 1,
                    "phase": "PHASE_2",
                },
                {"primitive_id": "flow.invoke", "version": 1, "phase": "PHASE_2"},
                {"primitive_id": "flow.loop", "version": 1, "phase": "PHASE_2"},
            ]
        }
    )
    assert "parallel.fork_join@1" in values
    assert "flow.invoke@1" in values
    assert "flow.loop@1" in values


def test_flow_invoke_and_flow_loop_render_first_class_capability_forms() -> None:
    invoke_out = _run_node_form(
        {
            "definition": PHASE2_DEFINITION,
            "selected_step_id": "invoke_root",
            "actions": [
                {
                    "kind": "change",
                    "attr": "data-am2-capability-key",
                    "value": "target_library",
                    "next_value": "other_subflow",
                }
            ],
        }
    )
    invoke_keys = _collect_attr_values(invoke_out["tree"], "data-am2-capability-key")
    assert "target_library" in invoke_keys
    assert "target_subflow" in invoke_keys
    assert invoke_out["patches"][-1]["inputs"]["target_library"] == "other_subflow"
    assert invoke_out["patches"][-1]["inputs"]["target_subflow"] == "other_subflow"

    loop_out = _run_node_form(
        {
            "definition": PHASE2_DEFINITION,
            "selected_step_id": "loop_root",
            "actions": [
                {
                    "kind": "change",
                    "attr": "data-am2-capability-key",
                    "value": "iterable_expr",
                    "next_value": "$.state.vars.next_items",
                }
            ],
        }
    )
    loop_keys = _collect_attr_values(loop_out["tree"], "data-am2-capability-key")
    assert {"iterable_expr", "item_var", "max_iterations"}.issubset(loop_keys)
    assert loop_out["patches"][-1]["inputs"]["iterable_expr"] == {"expr": "$.state.vars.next_items"}


def test_parallel_fork_join_supports_first_class_branch_authoring() -> None:
    out = _run_node_form(
        {
            "definition": PHASE2_DEFINITION,
            "selected_step_id": "fork_root",
            "actions": [{"kind": "click", "attr": "data-am2-capability-add", "value": "branch"}],
        }
    )
    assert "parallel.fork_join" in _collect_attr_values(out["tree"], "data-am2-capability-form")
    latest = out["patches"][-1]["inputs"]
    assert latest["branch_order"] == ["left", "branch_2"]
    assert latest["branches"]["branch_2"]["target_library"] == "named_subflow"


def test_library_panel_owns_library_authoring_ui_and_events() -> None:
    out = _run_library_panel(
        {
            "definition": PHASE2_DEFINITION,
            "state": {"selectedLibraryId": "named_subflow"},
            "actions": [
                {
                    "kind": "change",
                    "attr": "data-am2-library-param-name",
                    "value": "0",
                    "next_value": "display_name",
                },
                {
                    "kind": "click",
                    "attr": "data-am2-library-select",
                    "value": "other_subflow",
                },
            ],
        }
    )
    assert "true" in _collect_attr_values(out["tree"], "data-am2-library-panel")
    assert "named_subflow" in _collect_attr_values(out["tree"], "data-am2-library-editor")
    assert out["events"][0] == {
        "kind": "patch_library",
        "update": {"params": [{"name": "display_name", "required": True}]},
    }
    assert out["events"][1] == {"kind": "select_library", "value": "other_subflow"}


def test_graph_ops_support_library_scoped_phase2_authoring() -> None:
    out = _run_graph_ops(
        {
            "definition": PHASE2_DEFINITION,
            "actions": [
                {"kind": "set_selected_library", "value": "named_subflow"},
                {"kind": "add_library", "value": "helper_flow"},
                {
                    "kind": "patch_library",
                    "update": {"params": [{"name": "item", "required": False}]},
                },
                {
                    "kind": "add_primitive_node",
                    "item": {"primitive_id": "flow.loop", "version": 1},
                },
                {"kind": "set_selected_step", "value": "flow_loop"},
                {
                    "kind": "patch_node",
                    "update": {
                        "inputs": {
                            "iterable_expr": {"expr": "$.state.vars.helper_items"},
                            "item_var": "helper_item",
                            "max_iterations": 2,
                        }
                    },
                },
            ],
        }
    )
    wizard = out["snapshot"]["wizardDraft"]
    assert out["graph_label"] == "library:helper_flow"
    assert wizard["macros"]["fork_write"]["params"] == ["target_path"]
    assert wizard["libraries"]["helper_flow"]["params"] == [{"name": "item", "required": False}]
    assert wizard["libraries"]["helper_flow"]["nodes"][0]["op"]["primitive_id"] == "flow.loop"


def test_unknown_phase2_keys_survive_raw_json_apply_then_visual_edit() -> None:
    raw_text = json.dumps(PHASE2_DEFINITION, separators=(",", ":"))
    raw_out = _run_node(_RAW_JSON_SCRIPT, {"textarea_value": raw_text, "raw_mode": True})
    assert raw_out["events"] == [
        {"kind": "apply", "value": raw_text},
        {"kind": "mode", "value": False},
    ]

    applied = json.loads(raw_out["events"][0]["value"])
    node_out = _run_node_form(
        {
            "definition": applied,
            "graph_definition": applied["libraries"]["named_subflow"],
            "selected_step_id": "lib_prompt",
            "actions": [
                {
                    "kind": "change",
                    "attr": "data-am2-input-key",
                    "value": "label",
                    "next_value": "Display name",
                }
            ],
        }
    )
    assert node_out["patches"][-1]["inputs"]["label"] == "Display name"
    assert node_out["patches"][-1]["inputs"]["raw_only"] == {"nested": [1, 2]}


def test_node_form_delegates_phase2_controls_to_capability_module() -> None:
    source = Path("plugins/import/ui/web/assets/dsl_editor/node_form.js").read_text(
        encoding="utf-8"
    )
    assert "AM2DSLEditorCapabilityForms" in source
    assert "parallel.fork_join" not in source
    assert "flow.invoke" not in source
    assert "flow.loop" not in source
