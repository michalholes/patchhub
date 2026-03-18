"""Issue 106: v3 editor write defaults stay neutral and explicit."""

from __future__ import annotations

from pathlib import Path

GRAPH_OPS_PATH = Path("plugins/import/ui/web/assets/dsl_editor/graph_ops.js")
NODE_FORM_PATH = Path("plugins/import/ui/web/assets/dsl_editor/node_form.js")


def test_graph_ops_source_has_no_hidden_semantic_write_default() -> None:
    source = GRAPH_OPS_PATH.read_text(encoding="utf-8")

    assert "$.state.vars.value" not in source
    assert 'return { to_path: "", value: null };' in source
    assert "node.op.writes.push(createEmptyWrite());" in source


def test_node_form_roundtrips_neutral_write_state_without_semantic_fill() -> None:
    source = NODE_FORM_PATH.read_text(encoding="utf-8")

    assert "currentWriteItem(pathInput, valueInput)" in source
    assert "$.state.vars.value" not in source
