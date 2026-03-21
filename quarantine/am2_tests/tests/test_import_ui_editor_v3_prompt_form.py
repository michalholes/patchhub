"""Issue 110: first-class prompt primitive authoring controls."""

from __future__ import annotations

import json
import subprocess

_NODE_FORM_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.type = "";
    this.rows = 0;
    this.selected = false;
    this.listeners = {};
    this.dataset = {};
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    return child;
  }

  get firstChild() {
    return this.children.length ? this.children[0] : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "class") this.className = String(value);
    if (name === "type") this.type = String(value);
    if (name.startsWith("data-")) {
      this.dataset[name.slice(5)] = String(value);
    }
  }

  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
}

const document = {
  createElement(tag) {
    return new FakeNode(tag);
  },
};
const sandbox = {
  window: {},
  globalThis: {},
  document,
  console,
};
sandbox.globalThis = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(
    "plugins/import/ui/web/assets/dsl_editor/capability_forms.js",
    "utf8",
  ),
  sandbox,
  { filename: "capability_forms.js" },
);
vm.runInContext(
  fs.readFileSync("plugins/import/ui/web/assets/dsl_editor/node_form.js", "utf8"),
  sandbox,
  { filename: "node_form.js" },
);
const api = sandbox.window.AM2DSLEditorNodeForm;
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const mount = document.createElement("div");
const patches = [];
api.renderNodeForm({
  mount,
  definition: payload.definition,
  graphDefinition: payload.graph_definition || payload.definition,
  selectedStepId: payload.selected_step_id,
  actions: {
    onPatchNode(update) {
      patches.push(update);
    },
    onAddWrite() {},
    onPatchWrite() {},
    onRemoveNode() {},
    onRemoveWrite() {},
    onSelect() {},
  },
});

function visit(node, fn) {
  const pathNodes = new Set();
  let steps = 0;

  function walk(current) {
    if (!current) return;
    steps += 1;
    if (steps > 5000) {
      throw new Error("render tree traversal exceeded 5000 steps");
    }
    if (pathNodes.has(current)) {
      throw new Error("render tree traversal cycle detected");
    }
    pathNodes.add(current);
    fn(current);
    (current.children || []).forEach((child) => walk(child));
    pathNodes.delete(current);
  }

  walk(node);
}

function findByAttr(node, name, value) {
  let found = null;
  visit(node, (current) => {
    if (found) return;
    if (
      current &&
      current.attributes &&
      Object.prototype.hasOwnProperty.call(current.attributes, name) &&
      current.attributes[name] === String(value)
    ) {
      found = current;
    }
  });
  return found;
}

function trigger(action) {
  if (!action) return;
  const node = findByAttr(mount, action.attr, action.value);
  if (!node) {
    throw new Error("missing control: " + String(action.attr) + "=" + String(action.value));
  }
  if (action.kind === "change") {
    node.value = String(action.next_value || "");
    if (typeof node.listeners.change === "function") {
      node.listeners.change({ target: node });
    }
  }
  if (action.kind === "click" && typeof node.listeners.click === "function") {
    node.listeners.click({ target: node });
  }
}

(payload.actions || []).forEach(trigger);

function serialize(node) {
  return {
    tag: node.tagName,
    text: node.textContent,
    value: node.value,
    attrs: node.attributes,
    children: (node.children || []).map(serialize),
  };
}

process.stdout.write(JSON.stringify({ tree: serialize(mount), patches }));
"""


def _run_node_script(
    script: str, payload: dict[str, object], *, timeout: int = 5
) -> dict[str, object]:
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as err:
        raise AssertionError("Node editor harness timed out") from err
    return json.loads(proc.stdout)


def _run_node_form(payload: dict[str, object]) -> dict[str, object]:
    return _run_node_script(_NODE_FORM_SCRIPT, payload)


def _collect_attr_values(tree: dict[str, object], attr_name: str) -> list[str]:
    out: list[str] = []

    def visit(node: dict[str, object]) -> None:
        attrs = node.get("attrs") or {}
        if attr_name in attrs:
            out.append(str(attrs[attr_name]))
        for child in node.get("children") or []:
            visit(child)

    visit(tree)
    return out


def _find_text_for_attr(tree: dict[str, object], attr_name: str, attr_value: str) -> str | None:
    attrs = tree.get("attrs") or {}
    if attrs.get(attr_name) == attr_value:
        return str(tree.get("text") or "")
    for child in tree.get("children") or []:
        found = _find_text_for_attr(child, attr_name, attr_value)
        if found is not None:
            return found
    return None


PROMPT_DEFINITION = {
    "version": 3,
    "entry_step_id": "ask_name",
    "nodes": [
        {
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {
                    "label": "Display name",
                    "prompt": "Enter the display name",
                    "help": "Shown in the first-class form",
                    "hint": "Press Enter to keep the seed",
                    "examples": ["Ada", True],
                    "default_value": "fallback",
                    "prefill": "Ada",
                    "default_expr": {"expr": "$.state.vars.default_name"},
                    "prefill_expr": {"expr": "$.state.vars.prefill_name"},
                    "autofill_if": {"expr": "$.state.vars.should_autofill"},
                    "raw_only": {"nested": [1, 2]},
                },
                "writes": [],
            },
        }
    ],
    "edges": [],
}

MESSAGE_DEFINITION = {
    "version": 3,
    "entry_step_id": "hello",
    "nodes": [
        {
            "step_id": "hello",
            "op": {
                "primitive_id": "ui.message",
                "primitive_version": 1,
                "inputs": {
                    "text": "Hello",
                    "default_value": "ignored",
                    "autofill_if": {"expr": "$.state.vars.flag"},
                },
                "writes": [],
            },
        }
    ],
    "edges": [],
}


def test_prompt_primitives_render_first_class_metadata_controls() -> None:
    out = _run_node_form(
        {"definition": PROMPT_DEFINITION, "selected_step_id": "ask_name", "actions": []}
    )
    tree = out["tree"]

    control_keys = _collect_attr_values(tree, "data-am2-input-key")
    assert "label" in control_keys
    assert "prompt" in control_keys
    assert "help" in control_keys
    assert "hint" in control_keys
    assert "default_value" in control_keys
    assert "prefill" in control_keys
    assert "default_expr" in control_keys
    assert "prefill_expr" in control_keys
    assert "autofill_if" in control_keys
    assert "examples.0" in control_keys
    assert "examples.1" in control_keys
    assert "op.inputs" not in control_keys

    note_text = _find_text_for_attr(tree, "data-am2-note", "prompt-authoring")
    assert note_text == (
        "Prompt metadata is authored here. Raw JSON remains authoritative for advanced keys."
    )
    advanced_text = _find_text_for_attr(tree, "data-am2-note", "advanced-keys")
    assert advanced_text == "Advanced op.inputs keys are preserved in Raw JSON: raw_only"
    assert "parallelism" not in control_keys


def test_prompt_form_keeps_expr_shape_and_ui_message_stays_non_interactive() -> None:
    out = _run_node_form(
        {
            "definition": PROMPT_DEFINITION,
            "selected_step_id": "ask_name",
            "actions": [
                {
                    "kind": "change",
                    "attr": "data-am2-input-key",
                    "value": "default_expr",
                    "next_value": "$.state.vars.next_default",
                }
            ],
        }
    )
    assert out["patches"][-1]["inputs"] == {
        "label": "Display name",
        "prompt": "Enter the display name",
        "help": "Shown in the first-class form",
        "hint": "Press Enter to keep the seed",
        "examples": ["Ada", True],
        "default_value": "fallback",
        "prefill": "Ada",
        "default_expr": {"expr": "$.state.vars.next_default"},
        "prefill_expr": {"expr": "$.state.vars.prefill_name"},
        "autofill_if": {"expr": "$.state.vars.should_autofill"},
        "raw_only": {"nested": [1, 2]},
    }

    message_out = _run_node_form(
        {"definition": MESSAGE_DEFINITION, "selected_step_id": "hello", "actions": []}
    )
    message_tree = message_out["tree"]
    message_keys = _collect_attr_values(message_tree, "data-am2-input-key")

    assert "text" in message_keys
    assert "default_value" not in message_keys
    assert "prefill" not in message_keys
    assert "autofill_if" not in message_keys
    assert "label" not in message_keys
    assert "prompt" not in message_keys
    assert _find_text_for_attr(message_tree, "data-am2-note", "message-info") == (
        "ui.message@1 is non-interactive. It has no submit payload, defaults, or autofill."
    )


_PALETTE_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.type = "";
    this.listeners = {};
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    return child;
  }

  get firstChild() {
    return this.children.length ? this.children[0] : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "class") this.className = String(value);
    if (name === "type") this.type = String(value);
  }

  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
}

const document = { createElement(tag) { return new FakeNode(tag); } };
const sandbox = { window: {}, globalThis: {}, document, console };
sandbox.globalThis = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync("plugins/import/ui/web/assets/dsl_editor/palette.js", "utf8"),
  sandbox,
  { filename: "palette.js" },
);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const mount = document.createElement("div");
sandbox.window.AM2DSLEditorPalette.renderPalette({
  mount,
  registry: payload.registry,
  state: { onAddPrimitive() {}, onSearch() {}, searchText: payload.search_text || "" },
});

function visit(node, fn) {
  const pathNodes = new Set();
  let steps = 0;
  function walk(current) {
    if (!current) return;
    steps += 1;
    if (steps > 5000) throw new Error("render tree traversal exceeded 5000 steps");
    if (pathNodes.has(current)) throw new Error("render tree traversal cycle detected");
    pathNodes.add(current);
    fn(current);
    (current.children || []).forEach((child) => walk(child));
    pathNodes.delete(current);
  }
  walk(node);
}

const values = [];
visit(mount, (node) => {
  if (node && node.attributes && node.attributes["data-am2-palette-add"]) {
    values.push(String(node.attributes["data-am2-palette-add"]));
  }
});
process.stdout.write(JSON.stringify(values));
"""


def _run_palette(payload: dict[str, object]) -> list[str]:
    return _run_node_script(_PALETTE_SCRIPT, payload)


_LIBRARY_PANEL_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.type = "";
    this.listeners = {};
    this.dataset = {};
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    return child;
  }

  get firstChild() {
    return this.children.length ? this.children[0] : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "class") this.className = String(value);
    if (name === "type") this.type = String(value);
    if (name.startsWith("data-")) this.dataset[name.slice(5)] = String(value);
  }

  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
}

const document = { createElement(tag) { return new FakeNode(tag); } };
const sandbox = { window: {}, globalThis: {}, document, console };
sandbox.globalThis = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync("plugins/import/ui/web/assets/dsl_editor/library_panel.js", "utf8"),
  sandbox,
  { filename: "library_panel.js" },
);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const mount = document.createElement("div");
const events = [];
sandbox.window.AM2DSLEditorLibraryPanel.renderLibraryPanel({
  mount,
  definition: payload.definition,
  state: payload.state,
  actions: {
    onAddLibrary(value) { events.push({ kind: "add_library", value }); },
    onPatchLibrary(update) { events.push({ kind: "patch_library", update }); },
    onRemoveLibrary(value) { events.push({ kind: "remove_library", value }); },
    onSelectLibrary(value) { events.push({ kind: "select_library", value }); },
    onSelectRoot() { events.push({ kind: "select_root" }); },
  },
});

function visit(node, fn) {
  const pathNodes = new Set();
  let steps = 0;
  function walk(current) {
    if (!current) return;
    steps += 1;
    if (steps > 5000) throw new Error("render tree traversal exceeded 5000 steps");
    if (pathNodes.has(current)) throw new Error("render tree traversal cycle detected");
    pathNodes.add(current);
    fn(current);
    (current.children || []).forEach((child) => walk(child));
    pathNodes.delete(current);
  }
  walk(node);
}

function findByAttr(node, name, value) {
  let found = null;
  visit(node, (current) => {
    if (found) return;
    if (
      current &&
      current.attributes &&
      current.attributes[name] === String(value)
    ) found = current;
  });
  return found;
}

(payload.actions || []).forEach((action) => {
  const node = findByAttr(mount, action.attr, action.value);
  if (!node) {
    throw new Error(
      "missing control: " + String(action.attr) + "=" + String(action.value),
    );
  }
  if (action.kind === "change") {
    node.value = String(action.next_value || "");
    if (typeof node.listeners.change === "function") node.listeners.change({ target: node });
  }
  if (action.kind === "click" && typeof node.listeners.click === "function") {
    node.listeners.click({ target: node });
  }
});

function serialize(node) {
  return {
    tag: node.tagName,
    text: node.textContent,
    value: node.value,
    attrs: node.attributes,
    children: (node.children || []).map(serialize),
  };
}

process.stdout.write(JSON.stringify({ tree: serialize(mount), events }));
"""


def _run_library_panel(payload: dict[str, object]) -> dict[str, object]:
    return _run_node_script(_LIBRARY_PANEL_SCRIPT, payload)


_GRAPH_OPS_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");

const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const state = {
  wizardDraft: JSON.parse(JSON.stringify(payload.definition || {})),
  configDraft: {},
  selectedStepId: null,
};

const sandbox = {
  window: {},
  globalThis: {},
  console,
};
sandbox.globalThis = sandbox.window;
sandbox.window.AM2FlowEditorState = {
  getSnapshot() {
    return JSON.parse(JSON.stringify(state));
  },
  setSelectedStep(value) {
    state.selectedStepId = value == null ? null : String(value);
  },
  mutateWizard(mutator) {
    mutator(state.wizardDraft);
  },
  loadAll(bundle) {
    state.wizardDraft = JSON.parse(JSON.stringify(bundle.wizardDefinition || {}));
    state.configDraft = JSON.parse(JSON.stringify(bundle.flowConfig || {}));
  },
  markValidated() {},
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync("plugins/import/ui/web/assets/dsl_editor/graph_ops.js", "utf8"),
  sandbox,
  { filename: "graph_ops.js" },
);
const api = sandbox.window.AM2DSLEditorGraphOps;
(payload.actions || []).forEach((action) => {
  if (action.kind === "set_selected_library") api.setSelectedLibrary(action.value || "");
  if (action.kind === "set_selected_step") api.setSelectedStep(action.value || "");
  if (action.kind === "add_library") api.addLibrary(action.value || "library");
  if (action.kind === "patch_library") api.patchLibrary(action.update || {});
  if (action.kind === "add_primitive_node") api.addPrimitiveNode(action.item || {});
  if (action.kind === "patch_node") api.patchNode(action.update || {});
});
process.stdout.write(JSON.stringify({
  graph_label: api.currentGraphLabel(),
  snapshot: sandbox.window.AM2FlowEditorState.getSnapshot(),
}));
"""


def _run_graph_ops(payload: dict[str, object]) -> dict[str, object]:
    return _run_node_script(_GRAPH_OPS_SCRIPT, payload)
