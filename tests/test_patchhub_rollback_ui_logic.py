from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_queue_upload.js"
ROLLBACK_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_rollback.js"
STATE_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_rollback_state.js"


def _run_node(script: str) -> dict[str, object]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    proc = subprocess.run(
        [node, "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def _prelude() -> str:
    queue_path = json.dumps(str(QUEUE_PATH))
    rollback_path = json.dumps(str(ROLLBACK_PATH))
    state_path = json.dumps(str(STATE_PATH))
    return f"""
import fs from "fs";
import vm from "vm";
const queueSrc = fs.readFileSync({queue_path}, "utf8");
const rollbackSrc = fs.readFileSync({rollback_path}, "utf8");
const stateSrc = fs.readFileSync({state_path}, "utf8");
const elements = new Map();
const registry = new Map();
function makeClassList() {{
  const items = new Set();
  return {{
    add: (...names) => names.forEach((name) => items.add(String(name))),
    remove: (...names) => names.forEach((name) => items.delete(String(name))),
    toggle: (name, force) => {{
      const key = String(name);
      const enabled = force === undefined ? !items.has(key) : !!force;
      if (enabled) items.add(key); else items.delete(key);
      return enabled;
    }},
    contains: (name) => items.has(String(name)),
  }};
}}
function makeNode(id) {{
  return {{
    id,
    innerHTML: "",
    textContent: "",
    value: "",
    disabled: false,
    checked: false,
    style: {{}},
    parentElement: {{ classList: makeClassList() }},
    classList: makeClassList(),
    addEventListener() {{}},
    removeEventListener() {{}},
    appendChild() {{}},
    focus() {{}},
    setAttribute(name, value) {{ this[String(name)] = String(value); }},
    getAttribute(name) {{ return this[String(name)] || null; }},
  }};
}}
const runtime = {{
  register(name, exportsObj) {{
    registry.set(String(name || ""), exportsObj || {{}});
  }},
  call(name, ...args) {{
    for (const exportsObj of registry.values()) {{
      if (exportsObj && typeof exportsObj[name] === "function") {{
        return exportsObj[name](...args);
      }}
    }}
    return null;
  }},
}};
global.window = {{ PH: runtime }};
global.document = {{
  hidden: false,
  documentElement: {{ style: {{}} }},
  body: makeNode("body"),
  getElementById(id) {{
    const key = String(id || "");
    if (!elements.has(key)) elements.set(key, makeNode(key));
    return elements.get(key);
  }},
  createElement(tag) {{
    return makeNode(String(tag || "div"));
  }},
}};
global.el = (id) => document.getElementById(id);
global.normalizePatchPath = (value) => String(value || "");
global.getRawCommand = () => String(document.getElementById("rawCommand").value || "");
global.parseInFlight = false;
global.lastParsed = null;
global.lastParsedRaw = "";
global.clearParsedState = () => {{}};
global.setParseHint = () => {{}};
global.setPre = (_id, payload) => {{ global.__preview = payload; }};
global.setUiError = (message) => {{ global.__uiError = String(message || ""); }};
global.setUiStatus = (message) => {{ global.__uiStatus = String(message || ""); }};
global.setInfoPoolHint = (name, hint) => {{
  if (String(name || "") === "enqueue") global.__enqueueHint = String(hint || "");
}};
global.apiPost = () => Promise.resolve({{ ok: true }});
global.cfg = null;
global.dirty = {{ issueId: false, commitMsg: false, patchPath: false, targetRepo: false }};
[
  "mode",
  "issueId",
  "commitMsg",
  "patchPath",
  "browsePatch",
  "targetRepo",
  "rawCommand",
  "previewRight",
  "enqueueBtn",
  "rollbackSummary",
  "rollbackSourceSummary",
  "rollbackScopeSummary",
  "rollbackHelperBtn",
  "rollbackChooseSubsetBtn",
  "rollbackUseFullBtn",
].forEach((id) => document.getElementById(id));
vm.runInThisContext(stateSrc, {{ filename: {state_path} }});
vm.runInThisContext(rollbackSrc, {{ filename: {rollback_path} }});
vm.runInThisContext(queueSrc, {{ filename: {queue_path} }});
"""


def test_rollback_validation_hint_surfaces_instead_of_generic_missing_fields() -> None:
    script = (
        _prelude()
        + """
document.getElementById("mode").value = "rollback";
document.getElementById("targetRepo").value = "patchhub";
window.PH.call(
  "rollbackApplyState",
  {
    job_id: "job-source-389",
    issue_id: "389",
    commit_summary: "Repair rollback",
    effective_runner_target_repo: "patchhub",
  },
  {
    scope_kind: "full",
    selected_entry_count: 1,
    selected_entries: [{ entry_id: "entry_1" }],
    selected_repo_paths: ["scripts/patchhub_specification.md"],
    selected_entry_ids: ["entry_1"],
    can_execute: false,
    helper: { open: false },
  },
);
validateAndPreview();
process.stdout.write(JSON.stringify({
  hint: global.__enqueueHint || "",
  disabled: document.getElementById("enqueueBtn").disabled,
}));
"""
    )
    result = _run_node(script)
    assert result == {
        "hint": "guided rollback requires helper action or scope change",
        "disabled": True,
    }
