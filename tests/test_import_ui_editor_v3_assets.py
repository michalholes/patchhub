"""Issue 106: v3 editor assets are served and loaded explicitly."""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
build_router = import_module("plugins.import.ui_api").build_router

_HAS_FASTAPI = True
try:
    import fastapi  # noqa: F401
except Exception:
    _HAS_FASTAPI = False

try:
    import httpx  # noqa: F401

    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False


ASSET_PATHS = [
    "/import/ui/assets/flow_json_clipboard.js",
    "/import/ui/assets/flow_json_modal_dom.js",
    "/import/ui/assets/flow_json_file_io.js",
    "/import/ui/assets/dsl_editor/registry_api.js",
    "/import/ui/assets/dsl_editor/palette.js",
    "/import/ui/assets/dsl_editor/node_form.js",
    "/import/ui/assets/dsl_editor/edge_form.js",
    "/import/ui/assets/dsl_editor/raw_json.js",
    "/import/ui/assets/dsl_editor/graph_ops.js",
    "/import/ui/assets/dsl_editor/boot_v3.js",
    "/import/ui/assets/flow_json_modal_state.js",
    "/import/ui/assets/flow_json_modal_entrypoints.js",
]


def _make_engine(tmp_path: Path) -> Any:
    roots = {
        name: tmp_path / name
        for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
    }
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


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_import_ui_index_loads_v3_editor_assets_in_order(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    response = client.get("/import/ui/")
    assert response.status_code == 200
    html = response.text

    positions = []
    for asset_path in ASSET_PATHS:
        needle = f'<script src="{asset_path}"></script>'
        assert needle in html
        positions.append(html.index(needle))

    assert positions == sorted(positions)
    assert html.index("/import/ui/assets/dsl_editor/graph_ops.js") < html.index(
        "/import/ui/assets/dsl_editor/boot_v3.js"
    )
    assert html.index("/import/ui/assets/dsl_editor/boot_v3.js") < html.index(
        "/import/ui/assets/wizard_definition_editor.js"
    )
    assert html.index("/import/ui/assets/wizard_definition_editor.js") < html.index(
        "/import/ui/assets/flow_all_actions.js"
    )
    assert html.index("/import/ui/assets/flow_all_actions.js") < html.index(
        "/import/ui/assets/flow_json_modal_state.js"
    )
    assert html.index("/import/ui/assets/flow_json_file_io.js") < html.index(
        "/import/ui/assets/flow_json_modal_state.js"
    )
    assert html.index("/import/ui/assets/flow_json_modal_state.js") < html.index(
        "/import/ui/assets/flow_json_modal_entrypoints.js"
    )


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_import_ui_serves_v3_editor_assets(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    for asset_path in ASSET_PATHS:
        response = client.get(asset_path)
        assert response.status_code == 200, asset_path
        assert response.text


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_import_ui_index_exposes_flow_json_modal_controls(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    response = client.get("/import/ui/")
    assert response.status_code == 200
    html = response.text

    assert 'id="flowOpenWizardJson"' in html
    assert 'id="flowOpenConfigJson"' in html
    assert 'id="flowJsonModal"' in html
    assert 'id="flowJsonOpenFromFile"' in html
    assert 'id="flowJsonSaveToFile"' in html
    assert 'id="flowJsonModalClose"' in html
    assert 'id="flowJsonCopySelected"' in html
    assert 'id="flowJsonCopyAll"' in html
    assert 'id="flowJsonApply"' in html
    assert (
        '<link rel="stylesheet" href="/import/ui/assets/flow_json_modal.css" />' in html
    )
    assert html.index("/import/ui/assets/flow_json_file_io.js") < html.index(
        "/import/ui/assets/flow_json_modal_state.js"
    )
    assert html.index("/import/ui/assets/flow_json_modal_state.js") < html.index(
        "/import/ui/assets/flow_json_modal_entrypoints.js"
    )


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_import_ui_serves_flow_json_modal_layout_contract(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    css_response = client.get("/import/ui/assets/flow_json_modal.css")
    assert css_response.status_code == 200
    css = css_response.text
    assert "display: flex;" in css
    assert "flex-direction: column;" in css
    assert "overflow: hidden;" in css
    assert "flex: 1 1 320px;" in css
    assert "min-height: 180px;" in css
    assert "min-height: 520px;" not in css

    html_response = client.get("/import/ui/")
    assert html_response.status_code == 200
    html = html_response.text
    assert 'class="buttonRow flowJsonModalActionsBottom"' in html
    assert 'rows="16"' in html


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_BASE = REPO_ROOT / "plugins" / "import" / "ui" / "web" / "assets"


def _run_flow_json_modal_picker_scenario(body: str) -> dict[str, Any]:
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
    getAttribute(name) {{ return this.attributes[String(name)] || ""; }},
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
    select() {{
      this.selectionStart = 0;
      this.selectionEnd = String(this.value || "").length;
    }},
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
ensureNode("flowJsonModal").classList.add("is-hidden");
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
    config: {{ reload: async () => true, save: async () => true, activate: async () => true }},
    wizard: {{ reload: async () => true, save: async () => true }},
  }},
  AM2DSLEditorV3: {{ reloadAll: async () => true, activateDefinition: async () => true }},
  confirm: () => true,
  addEventListener: addWindowListener,
  removeEventListener: removeWindowListener,
  setTimeout,
  clearTimeout,
}};
Object.defineProperty(global, "navigator", {{
  value: {{ clipboard: {{ writeText: () => Promise.resolve() }} }},
  configurable: true,
  writable: true,
}});
global.window.navigator = global.navigator;
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
  execCommand(name) {{ return name === "copy"; }},
}};
global.CustomEvent = function(name, init) {{
  return {{ type: name, detail: init && init.detail }};
}};
vm.runInThisContext(src.clipboard);
vm.runInThisContext(src.dom);
vm.runInThisContext(src.fileIo);
vm.runInThisContext(src.state);
vm.runInThisContext(src.entrypoints);
(async () => {{
{body}
}})().catch((err) => {{
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}});
"""
    proc = subprocess.run(
        [node, "-e", script], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_flow_json_modal_open_from_file_survives_focus_before_change(
    tmp_path: Path,
) -> None:
    _make_engine(tmp_path)
    result = _run_flow_json_modal_picker_scenario(
        """
await window.AM2FlowJSONModalState.openModal("wizard");
global.__pickerBehavior = {
  mode: "select",
  focusFirst: true,
  changeDelay: 250,
  text: `
{
  "version": 3,
  "nodes": [{"step_id": "from_file"}]
}
`,
};
const opened = await window.AM2FlowJSONModalState.openFromFile();
process.stdout.write(JSON.stringify({
  opened,
  editorValue: document.getElementById("flowJsonModalEditor").value,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
}));
"""
    )
    assert result["opened"] is True
    assert '"step_id": "from_file"' in str(result["editorValue"])
    assert result["statusText"] == "JSON loaded from file."
    assert result["errorText"] == ""


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_flow_json_modal_open_from_file_cancel_still_returns_without_loading(
    tmp_path: Path,
) -> None:
    _make_engine(tmp_path)
    result = _run_flow_json_modal_picker_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
const before = document.getElementById("flowJsonModalEditor").value;
global.__pickerBehavior = {
  mode: "cancel",
  focusFirst: true,
  cancelDelay: 0,
};
const statusBefore = document.getElementById("flowJsonModalStatus").textContent;
const opened = await window.AM2FlowJSONModalState.openFromFile();
process.stdout.write(JSON.stringify({
  opened,
  before,
  after: document.getElementById("flowJsonModalEditor").value,
  statusBefore,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
}));
"""
    )
    assert result["opened"] is False
    assert result["after"] == result["before"]
    assert result["statusText"] == result["statusBefore"]
    assert result["errorText"] == ""


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_flow_json_modal_open_from_file_surfaces_fallback_exhaustion_error(
    tmp_path: Path,
) -> None:
    _make_engine(tmp_path)
    result = _run_flow_json_modal_picker_scenario(
        """
await window.AM2FlowJSONModalState.openModal("config");
const before = document.getElementById("flowJsonModalEditor").value;
global.__pickerBehavior = {
  focusFirst: true,
};
const opened = await window.AM2FlowJSONModalState.openFromFile();
process.stdout.write(JSON.stringify({
  opened,
  before,
  after: document.getElementById("flowJsonModalEditor").value,
  statusText: document.getElementById("flowJsonModalStatus").textContent,
  errorText: document.getElementById("flowJsonModalError").textContent,
}));
"""
    )
    assert result["opened"] is False
    assert result["after"] == result["before"]
    assert result["statusText"] == ""
    assert result["errorText"] == (
        "Error: Open from file failed after dialog close without a selected file."
    )


def test_flow_json_clipboard_falls_back_to_exec_command() -> None:
    result = _run_flow_json_modal_picker_scenario(
        """
global.navigator.clipboard.writeText = () => Promise.reject(new Error("denied"));
await window.AM2FlowJSONClipboard.copyText("fallback payload");
process.stdout.write(JSON.stringify({ bodyChildrenAfter: bodyChildren.length }));
"""
    )
    assert result["bodyChildrenAfter"] == 0
