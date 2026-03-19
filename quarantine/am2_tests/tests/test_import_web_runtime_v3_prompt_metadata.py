"""Issue 109: web runtime assets and v3 prompt metadata model."""

from __future__ import annotations

import json
import subprocess
from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
build_router = import_module("plugins.import.ui_api").build_router
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH

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


PROMPT_FLOW = {
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
                    "prompt": "Enter the final display name",
                    "help": "CLI and Web must render the same metadata",
                    "hint": "Press Enter to accept the backend prefill",
                    "examples": ["Ada", "Grace"],
                    "prefill": "Ada",
                },
                "writes": [],
            },
        }
    ],
    "edges": [],
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


def _run_v3_renderer(function_name: str, payload: dict) -> dict | bool | None:
    script = """
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("plugins/import/ui/web/assets/import_wizard_v3.js", "utf8");
const sandbox = { window: {}, globalThis: {}, console };
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "import_wizard_v3.js" });
const api = sandbox.window.AM2ImportWizardV3 || sandbox.globalThis.AM2ImportWizardV3;
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const out = api[payload.function_name](payload.argument);
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"function_name": function_name, "argument": payload}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(proc.stdout)


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_import_ui_index_loads_v3_runtime_assets_in_order(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    response = client.get("/import/ui/")
    assert response.status_code == 200
    html = response.text

    v3_tag = '<script src="/import/ui/assets/import_wizard_v3.js"></script>'
    legacy_tag = '<script src="/import/ui/assets/import_wizard.js"></script>'
    assert v3_tag in html
    assert legacy_tag in html
    assert html.index(v3_tag) < html.index(legacy_tag)


@pytest.mark.skipif(
    not Path("plugins/import/ui/web/assets/import_wizard_v3.js").exists(),
    reason="asset missing",
)
def test_import_wizard_v3_builds_prompt_model_from_step_ui(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PROMPT_FLOW)

    state = engine.create_session("inbox", "")
    step = engine.get_step_definition(state["session_id"], "ask_name")

    model = _run_v3_renderer("buildPromptModel", step)

    assert model == {
        "step_id": "ask_name",
        "primitive_id": "ui.prompt_text",
        "title": "ask_name",
        "label": "Display name",
        "prompt": "Enter the final display name",
        "help": "CLI and Web must render the same metadata",
        "hint": "Press Enter to accept the backend prefill",
        "examples": ["Ada", "Grace"],
        "items": [],
        "default_value": None,
        "prefill": "Ada",
    }


def _write_selection_tree(tmp_path: Path) -> None:
    for rel_path in ("A/Book1/a.txt", "B/Book2/b.txt"):
        path = tmp_path / "inbox" / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


def test_import_wizard_v3_builds_prompt_model_with_display_items(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    _write_selection_tree(tmp_path)

    state = engine.create_session("inbox", "")
    step = engine.get_step_definition(state["session_id"], "select_authors")

    model = _run_v3_renderer("buildPromptModel", step)

    assert model["items"] == [
        {"item_id": step["ui"]["items"][0]["item_id"], "label": "A"},
        {"item_id": step["ui"]["items"][1]["item_id"], "label": "B"},
    ]


def test_import_wizard_v3_render_keeps_existing_step_heading_when_items_refresh(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    _write_selection_tree(tmp_path)

    state = engine.create_session("inbox", "")
    state_view = engine.get_state(str(state["session_id"]))
    projected_step = engine.get_step_definition(
        str(state["session_id"]), "select_authors"
    )

    script = """
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('plugins/import/ui/web/assets/import_wizard_v3.js', 'utf8');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
function makeEl(tag, attrs) {
  return {
    tag,
    attrs: attrs || {},
    text: attrs && attrs.text ? String(attrs.text) : '',
    children: [],
    appendChild(child) { this.children.push(child); },
    replaceChildren(...nodes) { this.children = nodes; },
  };
}
function flatten(nodes) {
  const out = [];
  function visit(node) {
    if (!node || typeof node !== 'object') return;
    if (node.text) out.push(String(node.text));
    const kids = Array.isArray(node.children) ? node.children : [];
    kids.forEach(visit);
  }
  nodes.forEach(visit);
  return out;
}
const mount = {
  children: [makeEl('div', { text: 'Step: select_authors' })],
  appendChild(child) { this.children.push(child); },
  replaceChildren(...nodes) { this.children = nodes; },
};
const sandbox = {
  window: {
    fetch: async () => ({
      ok: true,
      text: async () => JSON.stringify(payload.projected_step),
    }),
  },
  globalThis: {},
  console,
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'import_wizard_v3.js' });
const api = sandbox.window.AM2ImportWizardV3 || sandbox.globalThis.AM2ImportWizardV3;
api.renderCurrentStep({ state: payload.state, mount, el: makeEl });
setTimeout(() => {
  process.stdout.write(JSON.stringify(flatten(mount.children)));
}, 20);
"""
    proc = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"projected_step": projected_step, "state": state_view}),
        text=True,
        capture_output=True,
        check=True,
    )

    flattened = json.loads(proc.stdout)
    assert flattened[0] == "Step: select_authors"
    assert "Options:" in flattened


def test_import_wizard_v3_fetches_current_step_projection_for_display_items(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    _write_selection_tree(tmp_path)

    state = engine.create_session("inbox", "")
    state_view = engine.get_state(str(state["session_id"]))
    projected_step = engine.get_step_definition(
        str(state["session_id"]), "select_authors"
    )

    script = """
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('plugins/import/ui/web/assets/import_wizard_v3.js', 'utf8');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
function makeEl(tag, attrs) {
  return {
    tag,
    attrs: attrs || {},
    text: attrs && attrs.text ? String(attrs.text) : '',
    children: [],
    appendChild(child) { this.children.push(child); },
  };
}
function flatten(nodes) {
  const out = [];
  function visit(node) {
    if (!node || typeof node !== 'object') return;
    if (node.text) out.push(String(node.text));
    const kids = Array.isArray(node.children) ? node.children : [];
    kids.forEach(visit);
  }
  nodes.forEach(visit);
  return out;
}
const mount = {
  children: [],
  appendChild(child) { this.children.push(child); },
  replaceChildren(...nodes) { this.children = nodes; },
};
const sandbox = {
  window: {
    fetch: async () => ({
      ok: true,
      text: async () => JSON.stringify(payload.projected_step),
    }),
  },
  globalThis: {},
  console,
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'import_wizard_v3.js' });
const api = sandbox.window.AM2ImportWizardV3 || sandbox.globalThis.AM2ImportWizardV3;
api.renderCurrentStep({ state: payload.state, mount, el: makeEl });
setTimeout(() => {
  process.stdout.write(JSON.stringify(flatten(mount.children)));
}, 20);
"""
    proc = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"projected_step": projected_step, "state": state_view}),
        text=True,
        capture_output=True,
        check=True,
    )

    flattened = json.loads(proc.stdout)
    assert "Options:" in flattened
    assert "1. A" in flattened
    assert "2. B" in flattened


def test_import_wizard_v3_builds_scoped_prompt_model_with_display_items(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    for rel_path in ("A/Book1/a.txt", "A/Book2/b.txt"):
        path = tmp_path / "inbox" / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    state = engine.create_session("inbox", "A")
    assert state["current_step_id"] == "select_books"
    step = engine.get_step_definition(state["session_id"], "select_books")

    model = _run_v3_renderer("buildPromptModel", step)

    assert model["items"] == [
        {"item_id": step["ui"]["items"][0]["item_id"], "label": "A / Book1"},
        {"item_id": step["ui"]["items"][1]["item_id"], "label": "A / Book2"},
    ]


def test_import_wizard_v3_does_not_fetch_projection_for_non_select_prompt(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PROMPT_FLOW)

    state = engine.create_session("inbox", "")
    state_view = engine.get_state(str(state["session_id"]))

    script = """
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('plugins/import/ui/web/assets/import_wizard_v3.js', 'utf8');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
function makeEl(tag, attrs) {
  return {
    tag,
    attrs: attrs || {},
    text: attrs && attrs.text ? String(attrs.text) : '',
    children: [],
    appendChild(child) { this.children.push(child); },
    replaceChildren(...nodes) { this.children = nodes; },
  };
}
let fetchCalls = 0;
const mount = {
  children: [],
  appendChild(child) { this.children.push(child); },
  replaceChildren(...nodes) { this.children = nodes; },
};
const sandbox = {
  window: {
    fetch: async () => {
      fetchCalls += 1;
      return { ok: true, text: async () => '{}' };
    },
  },
  globalThis: {},
  console,
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'import_wizard_v3.js' });
const api = sandbox.window.AM2ImportWizardV3 || sandbox.globalThis.AM2ImportWizardV3;
api.renderCurrentStep({ state: payload.state, mount, el: makeEl });
setTimeout(() => {
  process.stdout.write(JSON.stringify({ fetchCalls }));
}, 20);
"""
    proc = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"state": state_view}),
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(proc.stdout) == {"fetchCalls": 0}
