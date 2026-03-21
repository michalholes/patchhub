"""Issue 110: raw JSON stays authoritative and visual edits preserve unknown keys."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

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
  fs.readFileSync("plugins/import/ui/web/assets/dsl_editor/node_form.js", "utf8"),
  sandbox,
  { filename: "node_form.js" },
);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const mount = document.createElement("div");
const patches = [];
sandbox.window.AM2DSLEditorNodeForm.renderNodeForm({
  mount,
  definition: payload.definition,
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

const control = findByAttr(mount, "data-am2-input-key", payload.control_key);
if (!control) {
  throw new Error("missing control: " + String(payload.control_key));
}
control.value = String(payload.next_value || "");
if (typeof control.listeners.change === "function") {
  control.listeners.change({ target: control });
}
process.stdout.write(JSON.stringify(patches));
"""

_RAW_JSON_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");

class FakeClassList {
  constructor(node) {
    this.node = node;
    this.flags = new Set();
  }

  toggle(name, enabled) {
    if (enabled) this.flags.add(String(name));
    else this.flags.delete(String(name));
  }
}

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
    this.classList = new FakeClassList(this);
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
  fs.readFileSync("plugins/import/ui/web/assets/dsl_editor/raw_json.js", "utf8"),
  sandbox,
  { filename: "raw_json.js" },
);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const mount = document.createElement("div");
const textarea = document.createElement("textarea");
textarea.value = payload.textarea_value;
const events = [];
sandbox.window.AM2DSLEditorRawJSON.renderRawJSON({
  mount,
  textarea,
  state: { rawMode: payload.raw_mode },
  actions: {
    onApply(value) {
      events.push({ kind: "apply", value });
    },
    onSetMode(value) {
      events.push({ kind: "mode", value: !!value });
    },
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

const applyButton = findByAttr(mount, "data-am2-raw-json-apply", "true");
if (applyButton && typeof applyButton.listeners.click === "function") {
  applyButton.listeners.click({ target: applyButton });
}
const visualButton = findByAttr(mount, "data-am2-raw-json-toggle", "visual");
if (visualButton && typeof visualButton.listeners.click === "function") {
  visualButton.listeners.click({ target: visualButton });
}
process.stdout.write(
  JSON.stringify({
    events,
    textarea_hidden: textarea.classList.flags.has("is-hidden"),
    note_present: !!findByAttr(mount, "data-am2-raw-json-note", "authoritative"),
  }),
);
"""


def _run_node(script: str, payload: dict[str, Any]) -> Any:
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as err:
        raise AssertionError("Node editor harness timed out") from err
    return json.loads(proc.stdout)


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
                    "label": "Old label",
                    "prompt": "Prompt value",
                    "examples": ["Ada"],
                    "raw_only": {"nested": [1, 2, 3]},
                },
                "writes": [],
            },
        }
    ],
    "edges": [],
}


def test_visual_prompt_edit_preserves_unknown_raw_json_keys() -> None:
    patches = _run_node(
        _NODE_FORM_SCRIPT,
        {
            "definition": PROMPT_DEFINITION,
            "selected_step_id": "ask_name",
            "control_key": "label",
            "next_value": "New label",
        },
    )

    assert patches[-1]["inputs"] == {
        "label": "New label",
        "prompt": "Prompt value",
        "examples": ["Ada"],
        "raw_only": {"nested": [1, 2, 3]},
    }


def test_raw_json_mode_stays_authoritative_and_applies_exact_text() -> None:
    raw_text = '{"version":3,"nodes":[],"extra":{"raw_only":true}}'
    out = _run_node(
        _RAW_JSON_SCRIPT,
        {"textarea_value": raw_text, "raw_mode": True},
    )

    assert out["textarea_hidden"] is False
    assert out["note_present"] is True
    assert out["events"] == [
        {"kind": "apply", "value": raw_text},
        {"kind": "mode", "value": False},
    ]


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_BASE = REPO_ROOT / "plugins" / "import" / "ui" / "web" / "assets"


def _run_step_modal_picker_scenario(body: str) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script_paths = {
        "file_io": ASSET_BASE / "flow_json_file_io.js",
        "state": ASSET_BASE / "flow_step_modal_state.js",
    }
    script = f"""
const fs = require("fs");
const vm = require("vm");
const src = {{
  fileIo: fs.readFileSync({json.dumps(str(script_paths["file_io"]))}, "utf8"),
  state: fs.readFileSync({json.dumps(str(script_paths["state"]))}, "utf8"),
}};
const elements = new Map();
const bodyChildren = [];
const windowListeners = new Map();
const graphState = {{
  step: {{
    step_id: "effective_author_title",
    op: {{ primitive_id: "ui.prompt_text", primitive_version: 1 }},
  }},
}};
function addWindowListener(type, fn) {{
  const key = String(type);
  const items = windowListeners.get(key) || [];
  items.push(fn);
  windowListeners.set(key, items);
}}
function removeWindowListener(type, fn) {{
  const key = String(type);
  const items = windowListeners.get(key) || [];
  windowListeners.set(key, items.filter((item) => item !== fn));
}}
function dispatchWindowEvent(type) {{
  const items = (windowListeners.get(String(type)) || []).slice();
  items.forEach((fn) => fn({{ type }}));
}}
function makeClassList() {{
  const items = new Set(["is-hidden"]);
  return {{
    add: (...names) => names.forEach((name) => items.add(String(name))),
    remove: (...names) => names.forEach((name) => items.delete(String(name))),
    contains: (name) => items.has(String(name)),
    toggle: (name, force) => {{
      const key = String(name);
      if (force === true) {{ items.add(key); return true; }}
      if (force === false) {{ items.delete(key); return false; }}
      if (items.has(key)) {{ items.delete(key); return false; }}
      items.add(key);
      return true;
    }},
  }};
}}
function makeNode(id) {{
  const listeners = new Map();
  return {{
    id,
    nodeType: 1,
    textContent: "",
    value: "",
    selectionStart: 0,
    selectionEnd: 0,
    attributes: {{}},
    style: {{}},
    classList: makeClassList(),
    parentNode: null,
    setAttribute(name, value) {{ this.attributes[String(name)] = String(value); }},
    addEventListener(type, fn) {{
      const key = String(type);
      const items = listeners.get(key) || [];
      items.push(fn);
      listeners.set(key, items);
    }},
    removeEventListener(type, fn) {{
      const key = String(type);
      const items = listeners.get(key) || [];
      listeners.set(key, items.filter((item) => item !== fn));
    }},
    dispatch(type) {{
      const items = (listeners.get(String(type)) || []).slice();
      items.forEach((fn) => fn({{ preventDefault() {{}}, stopImmediatePropagation() {{}} }}));
    }},
    focus() {{}},
    replaceChildren() {{}},
  }};
}}
function makeInputNode() {{
  const input = makeNode("input");
  input.files = null;
  input.click = function () {{
    const behavior = global.__pickerBehavior || {{}};
    if (behavior.focusFirst === true) {{
      dispatchWindowEvent("focus");
    }}
    if (behavior.mode === "select") {{
      setTimeout(() => {{
        this.files = [{{ text: async () => String(behavior.text || "") }}];
        this.dispatch("change");
      }}, Number(behavior.changeDelay || 0));
      return;
    }}
    if (behavior.mode === "cancel") {{
      setTimeout(() => this.dispatch("cancel"), Number(behavior.cancelDelay || 0));
    }}
  }};
  return input;
}}
function ensureNode(id) {{
  const key = String(id);
  if (!elements.has(key)) elements.set(key, makeNode(key));
  return elements.get(key);
}}
[
  "flowStepModal",
  "flowStepModalTitle",
  "flowStepModalSubtitle",
  "flowStepModalDirtySummary",
  "flowStepModalStatus",
  "flowStepModalError",
  "flowStepModalBody",
  "flowStepModalJsonPanel",
  "flowStepModalActionStatus",
  "flowStepModalJsonEditor",
  "flowStepModalJsonReread",
  "flowStepModalJsonAbort",
  "flowStepModalJsonSave",
  "flowStepModalJsonOpenFromFile",
  "flowStepModalJsonSaveToFile",
  "flowStepModalJsonCopySelected",
  "flowStepModalJsonCopyAll",
  "flowStepModalTabForm",
  "flowStepModalTabJson",
  "flowStepModalValidate",
  "flowStepModalSave",
  "flowStepModalRestore",
  "flowStepModalClose",
].forEach(ensureNode);
global.window = {{
  AM2DSLEditorGraphOps: {{
    currentNode: () => graphState.step,
    selectedLibraryId: () => "library_1",
    setSelectedLibrary: () => {{}},
    setSelectedStep: (stepId) => {{ graphState.step.step_id = String(stepId || ""); }},
  }},
  AM2DSLEditorRegistryAPI: {{
    validateWizardDefinition: async () => ({{ ok: true, data: {{ definition: {{}} }} }}),
    saveWizardDefinition: async () => ({{ ok: true, data: {{}} }}),
    activateWizardDefinition: async () => ({{ ok: true, data: {{}} }}),
  }},
  AM2FlowStepModalForm: {{ renderForm: () => {{}} }},
  AM2FlowStepModalJSON: {{
    renderJSON: (cfg) => {{ cfg.textarea.value = String(cfg.value || ""); }},
  }},
  AM2FlowStepModalModel: {{
    pendingBufferCount: () => 0,
    workingStateDirty: (state) => state.jsonDirty === true,
    rebuildJsonBuffer: (state) => {{
      state.jsonBuffer = JSON.stringify(state.workingStep || {{}}, null, 2);
      state.jsonDirty = false;
    }},
    flushPendingEdits: () => true,
    flushField: () => true,
    isFieldDirty: () => false,
    readFieldValue: () => "",
    buildCandidateDefinition: () => ({{
      definition: {{}},
      nextStepId: "effective_author_title",
    }}),
    syncFromSavedStep: () => {{}},
  }},
  AM2FlowJSONClipboard: {{ copyText: () => Promise.resolve() }},
  addEventListener: addWindowListener,
  removeEventListener: removeWindowListener,
  setTimeout,
  clearTimeout,
  confirm: () => true,
  alert: () => undefined,
}};
global.document = {{
  body: {{
    appendChild(node) {{ node.parentNode = this; bodyChildren.push(node); return node; }},
    removeChild(node) {{
      const index = bodyChildren.indexOf(node);
      if (index >= 0) bodyChildren.splice(index, 1);
      node.parentNode = null;
      return node;
    }},
  }},
  getElementById(id) {{ return ensureNode(id); }},
  createElement(tag) {{
    return String(tag) === "input" ? makeInputNode() : makeNode(String(tag));
  }},
}};
vm.runInThisContext(src.fileIo);
vm.runInThisContext(src.state);
(async () => {{
{body}
}})().catch((err) => {{
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}});
"""
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def test_flow_step_modal_open_from_file_survives_focus_before_change() -> None:
    result = _run_step_modal_picker_scenario(
        """
await window.AM2FlowStepModalState.openStep("effective_author_title");
window.AM2FlowStepModalState.setView("json");
global.__pickerBehavior = {
  mode: "select",
  focusFirst: true,
  changeDelay: 250,
  text: (
    `
{
  "step_id": "effective_title",
` +
    `  "op": {"primitive_id": "ui.prompt_text"}
}
`
  ),
};
document.getElementById("flowStepModalJsonOpenFromFile").dispatch("click");
await new Promise((resolve) => setTimeout(resolve, 350));
process.stdout.write(JSON.stringify({
  jsonValue: document.getElementById("flowStepModalJsonEditor").value,
  statusText: document.getElementById("flowStepModalStatus").textContent,
  errorText: document.getElementById("flowStepModalError").textContent,
}));
"""
    )
    assert '"step_id": "effective_title"' in str(result["jsonValue"])
    assert result["statusText"] == "JSON loaded from file."
    assert result["errorText"] == ""


def test_flow_step_modal_open_from_file_surfaces_fallback_exhaustion_error() -> None:
    result = _run_step_modal_picker_scenario(
        """
await window.AM2FlowStepModalState.openStep("effective_author_title");
window.AM2FlowStepModalState.setView("json");
const before = document.getElementById("flowStepModalJsonEditor").value;
global.__pickerBehavior = {
  focusFirst: true,
};
document.getElementById("flowStepModalJsonOpenFromFile").dispatch("click");
await new Promise((resolve) => setTimeout(resolve, 1100));
process.stdout.write(JSON.stringify({
  before,
  after: document.getElementById("flowStepModalJsonEditor").value,
  statusText: document.getElementById("flowStepModalStatus").textContent,
  errorText: document.getElementById("flowStepModalError").textContent,
}));
"""
    )
    assert result["after"] == result["before"]
    assert result["statusText"] == ""
    assert result["errorText"] == (
        "Error: Open from file failed after dialog close without a selected file."
    )
