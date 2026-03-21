from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_BASE = REPO_ROOT / "plugins" / "import" / "ui" / "web" / "assets"


def _run_node_scenario(body: str) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script_paths = {
        "clipboard": ASSET_BASE / "flow_json_clipboard.js",
        "dom": ASSET_BASE / "flow_json_modal_dom.js",
        "file_io": ASSET_BASE / "flow_json_file_io.js",
        "state": ASSET_BASE / "flow_json_modal_state.js",
        "entrypoints": ASSET_BASE / "flow_json_modal_entrypoints.js",
    }
    script = f"""
const fs = require("fs");
const vm = require("vm");
const src = {{
  clipboard: fs.readFileSync({json.dumps(str(script_paths["clipboard"]))}, "utf8"),
  dom: fs.readFileSync({json.dumps(str(script_paths["dom"]))}, "utf8"),
  fileIo: fs.readFileSync({json.dumps(str(script_paths["file_io"]))}, "utf8"),
  state: fs.readFileSync({json.dumps(str(script_paths["state"]))}, "utf8"),
  entrypoints: fs.readFileSync({json.dumps(str(script_paths["entrypoints"]))}, "utf8"),
}};
const elements = new Map();
const bodyChildren = [];
const windowListeners = new Map();
function addWindowListener(type, fn) {{
  const key = String(type);
  const items = windowListeners.get(key) || [];
  items.push(fn);
  windowListeners.set(key, items);
}}
function removeWindowListener(type, fn) {{
  const key = String(type);
  const items = windowListeners.get(key) || [];
  windowListeners.set(
    key,
    items.filter((item) => item !== fn),
  );
}}
function dispatchWindowEvent(type, extra) {{
  const items = (windowListeners.get(String(type)) || []).slice();
  const event = Object.assign(
    {{
      type,
      key: "",
      target: null,
      preventDefault() {{}},
      stopImmediatePropagation() {{}},
    }},
    extra || {{}},
  );
  items.forEach((fn) => fn(event));
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
    toArray: () => Array.from(items),
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
    setAttribute(name, value) {{ this.attributes[String(name)] = String(value); }},
    getAttribute(name) {{ return this.attributes[String(name)] || ""; }},
    addEventListener(type, fn) {{ listeners.set(String(type), fn); }},
    removeEventListener(type) {{ listeners.delete(String(type)); }},
    dispatch(type, extra) {{
      const fn = listeners.get(String(type));
      if (!fn) return undefined;
      return fn(
        Object.assign(
          {{
            type,
            key: "",
            target: this,
            preventDefault() {{}},
            stopImmediatePropagation() {{}},
          }},
          extra || {{}},
        ),
      );
    }},
    focus() {{}},
    select() {{
      this.selectionStart = 0;
      this.selectionEnd = String(this.value || "").length;
    }},
  }};
}}
function ensureNode(id) {{
  const key = String(id);
  if (!elements.has(key)) elements.set(key, makeNode(key));
  return elements.get(key);
}}
[
  "flowJsonModal",
  "flowJsonModalTitle",
  "flowJsonModalSubtitle",
  "flowJsonModalEditor",
  "flowJsonModalStatus",
  "flowJsonModalError",
  "flowJsonReread",
  "flowJsonAbort",
  "flowJsonSave",
  "flowJsonOpenFromFile",
  "flowJsonSaveToFile",
  "flowJsonModalClose",
  "flowJsonCancel",
  "flowJsonCopySelected",
  "flowJsonCopyAll",
  "flowJsonApply",
  "flowOpenWizardJson",
  "flowOpenConfigJson",
].forEach(ensureNode);
const modal = ensureNode("flowJsonModal");
modal.classList.add("is-hidden");
const editor = ensureNode("flowJsonModalEditor");
const confirmCalls = [];
const clipboardCalls = [];
const actionCounts = {{
  configReload: 0,
  configSave: 0,
  configActivate: 0,
  wizardReload: 0,
  wizardSave: 0,
  wizardActivate: 0,
}};
const state = {{
  wizardDraft: {{ version: 3, nodes: [{{ step_id: "s1" }}], _am2_ui: {{ keep: true }} }},
  configDraft: {{ version: 1, defaults: {{ marker: 1 }} }},
  selectedStepId: "s1",
  draftDirty: false,
}};
const flowEditor = {{
  getSnapshot() {{ return state; }},
  mutateConfig(mutator) {{ mutator(state.configDraft); state.draftDirty = true; }},
  mutateWizard(mutator) {{ mutator(state.wizardDraft); state.draftDirty = true; }},
}};
global.window = {{
  navigator: null,
  AM2EditorHTTP: {{ pretty: (obj) => JSON.stringify(obj, null, 2) }},
  AM2FlowEditorState: flowEditor,
  AM2FlowEditor: {{
    config: {{
      reload: async () => {{
        actionCounts.configReload += 1;
        state.configDraft = {{ version: 1, defaults: {{ marker: 7 }} }};
        state.draftDirty = false;
        return true;
      }},
      save: async () => {{
        actionCounts.configSave += 1;
        state.configDraft.saved = true;
        state.draftDirty = false;
        return true;
      }},
      activate: async () => {{
        actionCounts.configActivate += 1;
        state.configDraft.activated = true;
        state.draftDirty = false;
        return true;
      }},
    }},
    wizard: {{
      reload: async () => {{
        actionCounts.wizardReload += 1;
        state.wizardDraft = {{
          version: 3,
          nodes: [{{ step_id: "server" }}],
          _am2_ui: {{ flag: true }},
        }};
        state.draftDirty = false;
        return true;
      }},
      save: async () => {{
        actionCounts.wizardSave += 1;
        state.wizardDraft.saved = true;
        state.draftDirty = false;
        return true;
      }},
    }},
  }},
  AM2DSLEditorV3: {{
    reloadAll: async () => {{
      actionCounts.wizardReload += 1;
      state.wizardDraft = {{
        version: 3,
        nodes: [{{ step_id: "server" }}],
        _am2_ui: {{ flag: true }},
      }};
      state.draftDirty = false;
      return true;
    }},
    activateDefinition: async () => {{
      actionCounts.wizardActivate += 1;
      state.wizardDraft.activated = true;
      state.draftDirty = false;
      return true;
    }},
  }},
  confirm(message) {{ confirmCalls.push(String(message)); return true; }},
  addEventListener: addWindowListener,
  removeEventListener: removeWindowListener,
}};
Object.defineProperty(global, "navigator", {{
  value: {{
    clipboard: {{
      writeText: (text) => {{ clipboardCalls.push(String(text)); return Promise.resolve(); }},
    }},
  }},
  configurable: true,
  writable: true,
}});
global.window.navigator = global.navigator;
global.document = {{
  body: {{
    appendChild(node) {{ bodyChildren.push(node); return node; }},
    removeChild(node) {{
      const index = bodyChildren.indexOf(node);
      if (index >= 0) bodyChildren.splice(index, 1);
      return node;
    }},
  }},
  getElementById(id) {{ return ensureNode(id); }},
  createElement(tag) {{ return makeNode(String(tag)); }},
  execCommand(name) {{ return name === "copy"; }},
}};
global.CustomEvent = function(name, init) {{
  return {{ type: name, detail: init && init.detail }};
}};
vm.runInThisContext(src.clipboard, {{ filename: {json.dumps(str(script_paths["clipboard"]))} }});
vm.runInThisContext(src.dom, {{ filename: {json.dumps(str(script_paths["dom"]))} }});
vm.runInThisContext(src.fileIo, {{ filename: {json.dumps(str(script_paths["file_io"]))} }});
vm.runInThisContext(src.state, {{ filename: {json.dumps(str(script_paths["state"]))} }});
vm.runInThisContext(
  src.entrypoints,
  {{ filename: {json.dumps(str(script_paths["entrypoints"]))} }},
);
(async () => {{
{body}
}})().catch((err) => {{
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}});
"""
    proc = subprocess.run([node, "-e", script], cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def test_flow_json_modal_close_affordance_and_escape_match_cancel() -> None:
    result = _run_node_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
document.getElementById("flowJsonModalClose").dispatch("click");
const hiddenAfterHeaderClose = document.getElementById("flowJsonModal").classList.contains(
  "is-hidden",
);
await window.AM2FlowJSONModalState.openModal("wizard");
dispatchWindowEvent("keydown", { key: "Escape" });
process.stdout.write(JSON.stringify({
  hiddenAfterHeaderClose,
  hiddenAfterEscape: document.getElementById("flowJsonModal").classList.contains(
    "is-hidden",
  ),
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
}));
"""
    )
    assert result["hiddenAfterHeaderClose"] is True
    assert result["hiddenAfterEscape"] is True
    assert result["statusText"] == ""
    assert result["errorText"] == ""


def test_flow_json_modal_open_abort_cancel_and_reread() -> None:
    result = _run_node_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
const editorNode = document.getElementById("flowJsonModalEditor");
const firstValue = editorNode.value;
editorNode.value = `\n{\n  "version": 1,\n  "defaults": {\n    "marker": 99\n  }\n}`;
window.AM2FlowJSONModalState.abortChanges();
const afterAbort = editorNode.value;
window.AM2FlowJSONModalState.cancelModal();
const hiddenAfterCancel = document.getElementById("flowJsonModal").classList.contains("is-hidden");
state.draftDirty = true;
await window.AM2FlowJSONModalState.openModal("wizard");
process.stdout.write(JSON.stringify({
  firstValue,
  afterAbort,
  hiddenAfterCancel,
  confirmCalls,
  actionCounts,
  wizardTitle: document.getElementById("flowJsonModalTitle").textContent,
  wizardValue: document.getElementById("flowJsonModalEditor").value,
}));
"""
    )
    assert '"marker": 7' in str(result["firstValue"])
    assert result["afterAbort"] == result["firstValue"]
    assert result["hiddenAfterCancel"] is True
    assert result["actionCounts"]["configReload"] == 1
    assert result["actionCounts"]["wizardReload"] == 1
    assert result["confirmCalls"] == [
        "Discard current unsaved Flow Editor changes and re-read the server draft?"
    ]
    assert result["wizardTitle"] == "Wizard JSON"
    assert '"step_id": "server"' in str(result["wizardValue"])
    assert "_am2_ui" not in str(result["wizardValue"])


def test_flow_json_modal_save_apply_and_copy_actions() -> None:
    result = _run_node_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
const editorNode = document.getElementById("flowJsonModalEditor");
editorNode.value = `\n{\n  "version": 1,\n  "defaults": {\n    "marker": 11\n  }\n}`;
await window.AM2FlowJSONModalState.saveDraft();
editorNode.selectionStart = 20;
editorNode.selectionEnd = 34;
await window.AM2FlowJSONModalState.copySelected();
await window.AM2FlowJSONModalState.copyAll();
await window.AM2FlowJSONModalState.applyForFutureRuns();
await window.AM2FlowJSONModalState.openModal("wizard");
const wizardEditor = document.getElementById("flowJsonModalEditor");
wizardEditor.value = (
    `\n{\n  "version": 3,\n  "nodes": [\n    {\n      "step_id": "wiz_edited"\n    }\n  ]\n}`
);
await window.AM2FlowJSONModalState.saveDraft();
await window.AM2FlowJSONModalState.applyForFutureRuns();
process.stdout.write(JSON.stringify({
  actionCounts,
  clipboardCalls,
  configDraft: state.configDraft,
  wizardDraft: state.wizardDraft,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
}));
"""
    )
    assert result["actionCounts"]["configSave"] == 1
    assert result["actionCounts"]["configActivate"] == 1
    assert result["actionCounts"]["wizardSave"] == 1
    assert result["actionCounts"]["wizardActivate"] == 1
    assert result["configDraft"]["defaults"]["marker"] == 11
    assert result["configDraft"]["saved"] is True
    assert result["configDraft"]["activated"] is True
    assert result["wizardDraft"]["nodes"][0]["step_id"] == "wiz_edited"
    assert result["wizardDraft"]["saved"] is True
    assert result["wizardDraft"]["activated"] is True
    assert len(result["clipboardCalls"]) == 2
    assert '"marker": 11' in result["clipboardCalls"][1]
    assert result["statusText"] == "Applied for future runs."
    assert result["errorText"] == ""


def test_flow_json_modal_rejects_switch_without_artifact_drift() -> None:
    result = _run_node_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
const editorNode = document.getElementById("flowJsonModalEditor");
editorNode.value = (`\n{\n  "version": 1,\n  "defaults": {\n    "marker": 55\n  }\n}`);
window.AM2FlowJSONModalState.cancelModal();
window.confirm = (message) => {
  confirmCalls.push(String(message));
  return false;
};
const switched = await window.AM2FlowJSONModalState.openModal("wizard");
await window.AM2FlowJSONModalState.saveDraft();
process.stdout.write(JSON.stringify({
  switched,
  confirmCalls,
  actionCounts,
  modalHidden: document.getElementById("flowJsonModal").classList.contains("is-hidden"),
  modalTitle: document.getElementById("flowJsonModalTitle").textContent,
  editorValue: document.getElementById("flowJsonModalEditor").value,
  configDraft: state.configDraft,
  wizardDraft: state.wizardDraft,
}));
"""
    )
    assert result["switched"] is False
    assert result["confirmCalls"] == ["Discard modal changes and re-read the server draft?"]
    assert result["modalHidden"] is True
    assert result["modalTitle"] == "FlowConfig JSON"
    assert '"marker": 55' in str(result["editorValue"])
    assert result["actionCounts"]["configSave"] == 1
    assert result["actionCounts"]["wizardSave"] == 0
    assert result["configDraft"]["defaults"]["marker"] == 55
    assert result["configDraft"]["saved"] is True
    assert result["wizardDraft"]["nodes"][0]["step_id"] == "s1"
    assert "saved" not in result["wizardDraft"]


def test_flow_json_modal_rejects_initial_open_when_flow_editor_has_unsaved_changes() -> None:
    result = _run_node_scenario(
        """
state.draftDirty = true;
window.confirm = (message) => {
  confirmCalls.push(String(message));
  return false;
};
const opened = await window.AM2FlowJSONModalState.openModal("wizard");
process.stdout.write(JSON.stringify({
  opened,
  confirmCalls,
  actionCounts,
  modalHidden: document.getElementById("flowJsonModal").classList.contains("is-hidden"),
  modalTitle: document.getElementById("flowJsonModalTitle").textContent,
  editorValue: document.getElementById("flowJsonModalEditor").value,
}));
"""
    )
    assert result["opened"] is False
    assert result["confirmCalls"] == [
        "Discard current unsaved Flow Editor changes and re-read the server draft?"
    ]
    assert result["actionCounts"]["wizardReload"] == 0
    assert result["actionCounts"]["configReload"] == 0
    assert result["modalHidden"] is True
    assert result["modalTitle"] == ""
    assert result["editorValue"] == ""


def test_flow_json_modal_open_from_file_marks_editor_dirty_and_abort_restores_server() -> None:
    result = _run_node_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
const editorNode = document.getElementById("flowJsonModalEditor");
const loadedValue = editorNode.value;
window.AM2FlowJSONFileIO.setHooks({
  openTextFile: async (artifact) => ({
    cancelled: false,
    text: (`
{
  "artifact": "${artifact}",
  "defaults": {
    "marker": 88
  }
}`),
  }),
});
const openedConfig = await window.AM2FlowJSONModalState.openFromFile();
const dirtyAfterConfig = editorNode.value !== loadedValue;
const configValue = editorNode.value;
window.AM2FlowJSONModalState.abortChanges();
const afterAbort = editorNode.value;
await window.AM2FlowJSONModalState.openModal("wizard");
const wizardEditor = document.getElementById("flowJsonModalEditor");
const wizardServerValue = wizardEditor.value;
window.AM2FlowJSONFileIO.setHooks({
  openTextFile: async (artifact) => ({
    cancelled: false,
    text: (`
{
  "artifact": "${artifact}",
  "nodes": [
    {
      "step_id": "wiz_local"
    }
  ]
}`),
  }),
});
const openedWizard = await window.AM2FlowJSONModalState.openFromFile();
const wizardDirty = wizardEditor.value !== wizardServerValue;
process.stdout.write(JSON.stringify({
  openedConfig,
  openedWizard,
  dirtyAfterConfig,
  wizardDirty,
  loadedValue,
  configValue,
  afterAbort,
  wizardValue: wizardEditor.value,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
  configDraft: state.configDraft,
  wizardDraft: state.wizardDraft,
}));
"""
    )
    assert result["openedConfig"] is True
    assert result["openedWizard"] is True
    assert result["dirtyAfterConfig"] is True
    assert result["wizardDirty"] is True
    assert '"marker": 88' in str(result["configValue"])
    assert result["afterAbort"] == result["loadedValue"]
    assert '"step_id": "wiz_local"' in str(result["wizardValue"])
    assert result["statusText"] == "JSON loaded from file."
    assert result["errorText"] == ""
    assert result["configDraft"]["defaults"]["marker"] == 7
    assert result["wizardDraft"]["nodes"][0]["step_id"] == "server"


def test_flow_json_modal_save_to_file_uses_exact_editor_text_and_filenames() -> None:
    result = _run_node_scenario(
        """
const saved = [];
window.AM2FlowJSONFileIO.setHooks({
  saveTextFile: async (artifact, text) => {
    saved.push({
      artifact,
      text,
      filename: window.AM2FlowJSONFileIO.fileNameForArtifact(artifact),
    });
  },
});
await window.AM2FlowJSONModalState.openModal("config");
const editorNode = document.getElementById("flowJsonModalEditor");
editorNode.value = (`
{
  "version": 1,
  "defaults": {
    "marker": 31
  }
}`);
await window.AM2FlowJSONModalState.saveToFile();
await window.AM2FlowJSONModalState.openModal("wizard");
const wizardEditor = document.getElementById("flowJsonModalEditor");
wizardEditor.value = (`
{
  "version": 3,
  "nodes": [
    {
      "step_id": "wiz_save"
    }
  ]
}`);
await window.AM2FlowJSONModalState.saveToFile();
process.stdout.write(JSON.stringify({
  saved,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
  configDraft: state.configDraft,
  wizardDraft: state.wizardDraft,
}));
"""
    )
    assert result["saved"][0]["artifact"] == "config"
    assert result["saved"][0]["filename"] == "flow_config_draft.json"
    assert result["saved"][0]["text"].endswith('"marker": 31\n  }\n}')
    assert result["saved"][1]["artifact"] == "wizard"
    assert result["saved"][1]["filename"] == "wizard_definition_draft.json"
    assert '"step_id": "wiz_save"' in result["saved"][1]["text"]
    assert result["statusText"] == "JSON saved to file."
    assert result["errorText"] == ""
    assert result["configDraft"]["defaults"]["marker"] == 7
    assert result["wizardDraft"]["nodes"][0]["step_id"] == "server"


def test_flow_json_modal_open_from_file_cancel_and_failures_are_noop_or_error() -> None:
    result = _run_node_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
const editorNode = document.getElementById("flowJsonModalEditor");
const serverValue = editorNode.value;
window.AM2FlowJSONFileIO.setHooks({
  openTextFile: async () => ({ cancelled: true, text: "" }),
});
const cancelled = await window.AM2FlowJSONModalState.openFromFile();
const afterCancel = editorNode.value;
editorNode.value = (`
{
  "version": 1,
  "defaults": {
    "marker": 999
  }
}`);
window.confirm = (message) => {
  confirmCalls.push(String(message));
  return false;
};
const rejectedDirtyOpen = await window.AM2FlowJSONModalState.openFromFile();
const afterRejectedDirtyOpen = editorNode.value;
window.confirm = (message) => {
  confirmCalls.push(String(message));
  return true;
};
window.AM2FlowJSONFileIO.setHooks({
  openTextFile: async () => {
    throw new Error("read exploded");
  },
});
const failedOpen = await window.AM2FlowJSONModalState.openFromFile();
const openError = document.getElementById("flowJsonModalError").textContent;
window.AM2FlowJSONFileIO.setHooks({
  saveTextFile: async () => {
    throw new Error("write exploded");
  },
});
const failedSave = await window.AM2FlowJSONModalState.saveToFile();
process.stdout.write(JSON.stringify({
  cancelled,
  afterCancel,
  serverValue,
  rejectedDirtyOpen,
  afterRejectedDirtyOpen,
  failedOpen,
  openError,
  failedSave,
  saveError: document.getElementById("flowJsonModalError").textContent,
  confirmCalls,
  configDraft: state.configDraft,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
}));
"""
    )
    assert result["cancelled"] is False
    assert result["afterCancel"] == result["serverValue"]
    assert result["rejectedDirtyOpen"] is False
    assert result["afterRejectedDirtyOpen"] != result["serverValue"]
    assert result["confirmCalls"] == [
        "Discard current modal changes and open JSON from file?",
        "Discard current modal changes and open JSON from file?",
    ]
    assert result["failedOpen"] is False
    assert result["openError"] == "Error: read exploded"
    assert result["failedSave"] is False
    assert result["saveError"] == "Error: write exploded"
    assert result["configDraft"]["defaults"]["marker"] == 7
    assert result["statusText"] == ""


def test_flow_json_modal_keeps_closed_state_when_initial_open_reload_fails() -> None:
    result = _run_node_scenario(
        """
window.AM2FlowEditor.config.reload = async () => {
  actionCounts.configReload += 1;
  return false;
};
const opened = await window.AM2FlowJSONModalState.openModal("config");
process.stdout.write(JSON.stringify({
  opened,
  actionCounts,
  modalHidden: document.getElementById("flowJsonModal").classList.contains("is-hidden"),
  modalTitle: document.getElementById("flowJsonModalTitle").textContent,
  modalSubtitle: document.getElementById("flowJsonModalSubtitle").textContent,
  editorValue: document.getElementById("flowJsonModalEditor").value,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
}));
"""
    )
    assert result["opened"] is False
    assert result["actionCounts"]["configReload"] == 1
    assert result["modalHidden"] is True
    assert result["modalTitle"] == ""
    assert result["modalSubtitle"] == ""
    assert result["editorValue"] == ""
    assert result["statusText"] == ""
    assert result["errorText"] == ""


def test_flow_json_modal_keeps_previous_artifact_when_switch_reload_fails() -> None:
    result = _run_node_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
window.AM2DSLEditorV3.reloadAll = async () => {
  actionCounts.wizardReload += 1;
  return false;
};
window.AM2FlowEditor.wizard.reload = async () => {
  actionCounts.wizardReload += 1;
  return false;
};
const switched = await window.AM2FlowJSONModalState.openModal("wizard");
await window.AM2FlowJSONModalState.saveDraft();
await window.AM2FlowJSONModalState.applyForFutureRuns();
process.stdout.write(JSON.stringify({
  switched,
  actionCounts,
  modalHidden: document.getElementById("flowJsonModal").classList.contains("is-hidden"),
  modalTitle: document.getElementById("flowJsonModalTitle").textContent,
  modalSubtitle: document.getElementById("flowJsonModalSubtitle").textContent,
  editorValue: document.getElementById("flowJsonModalEditor").value,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
  configDraft: state.configDraft,
  wizardDraft: state.wizardDraft,
}));
"""
    )
    assert result["switched"] is False
    assert result["actionCounts"]["wizardReload"] == 1
    assert result["modalHidden"] is False
    assert result["modalTitle"] == "FlowConfig JSON"
    assert "runtime defaults" in str(result["modalSubtitle"])
    assert '"marker": 7' in str(result["editorValue"])
    assert result["actionCounts"]["configSave"] == 1
    assert result["actionCounts"]["configActivate"] == 1
    assert result["actionCounts"]["wizardSave"] == 0
    assert result["actionCounts"]["wizardActivate"] == 0
    assert result["statusText"] == "Applied for future runs."
    assert result["errorText"] == ""
    assert result["configDraft"]["saved"] is True
    assert result["configDraft"]["activated"] is True
    assert "saved" not in result["wizardDraft"]
    assert "activated" not in result["wizardDraft"]
