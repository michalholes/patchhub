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
HELPER_MODAL_PATH = (
    REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_rollback_helper_modal.js"
)
TEMPLATE_PATH = REPO_ROOT / "scripts" / "patchhub" / "templates" / "index.html"


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
    helper_modal_path = json.dumps(str(HELPER_MODAL_PATH))
    return f"""
import fs from "fs";
import vm from "vm";
const queueSrc = fs.readFileSync({queue_path}, "utf8");
const rollbackSrc = fs.readFileSync({rollback_path}, "utf8");
const stateSrc = fs.readFileSync({state_path}, "utf8");
const helperModalSrc = fs.readFileSync({helper_modal_path}, "utf8");
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
  const node = {{
    id,
    innerHTML: "",
    textContent: "",
    value: "",
    disabled: false,
    checked: false,
    style: {{}},
    dataset: {{}},
    parentElement: {{ classList: makeClassList() }},
    classList: makeClassList(),
    addEventListener() {{}},
    removeEventListener() {{}},
    appendChild() {{}},
    focus() {{}},
    removeAttribute(name) {{
      delete this[String(name)];
      if (String(name) === "tabindex") delete this.tabIndex;
    }},
    setAttribute(name, value) {{ this[String(name)] = String(value); }},
    getAttribute(name) {{ return this[String(name)] || null; }},
    closest(selector) {{ return selector === "#" + this.id ? this : null; }},
  }};
  return node;
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
  addEventListener() {{}},
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
global.AMP_PATCHHUB_UI = {{ activeListModalController: null }};
window.AMP_PATCHHUB_UI = global.AMP_PATCHHUB_UI;
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
  "rollbackSubsetStrip",
  "rollbackHelperModal",
  "rollbackHelperTitle",
  "rollbackHelperBody",
  "rollbackHelperActions",
  "rollbackHelperCloseBtn",
  "rollbackHelperDoneBtn",
].forEach((id) => document.getElementById(id));
vm.runInThisContext(stateSrc, {{ filename: {state_path} }});
vm.runInThisContext(rollbackSrc, {{ filename: {rollback_path} }});
vm.runInThisContext(helperModalSrc, {{ filename: {helper_modal_path} }});
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


def test_full_scope_reuse_skips_duplicate_preflight_request() -> None:
    script = (
        _prelude()
        + """
document.getElementById("mode").value = "rollback";
document.getElementById("targetRepo").value = "patchhub";
let calls = 0;
global.apiPost = (path, body) => {
  calls += 1;
  return Promise.resolve({ ok: true, path, body });
};
window.PH.call(
  "rollbackApplyState",
  {
    job_id: "job-source-390",
    issue_id: "390",
    commit_summary: "Rollback source",
    effective_runner_target_repo: "patchhub",
  },
  {
    scope_kind: "full",
    selected_entry_count: 1,
    selected_entries: [{ entry_id: "entry_1" }],
    selected_repo_paths: ["scripts/patchhub/app_api_jobs.py"],
    selected_entry_ids: ["entry_1"],
    rollback_preflight_token: "tok-390",
    can_execute: true,
    helper: { open: false },
  },
);
window.PH.call("rollbackUseFullScope");
process.stdout.write(JSON.stringify({
  calls,
  scopeKind: window.PH.call("rollbackGetState").scopeKind,
  hint: global.__enqueueHint || "",
}));
"""
    )
    result = _run_node(script)
    assert result == {"calls": 0, "scopeKind": "full", "hint": ""}


def test_helper_modal_opens_automatically_without_manual_button() -> None:
    script = (
        _prelude()
        + """
document.getElementById("mode").value = "rollback";
document.getElementById("targetRepo").value = "patchhub";
window.PH.call(
  "rollbackApplyState",
  {
    job_id: "job-source-390-helper",
    issue_id: "390",
    commit_summary: "Needs helper",
    effective_runner_target_repo: "patchhub",
  },
  {
    scope_kind: "full",
    selected_entry_count: 1,
    selected_entries: [{ entry_id: "entry_1", label: "scripts/patchhub/app_api_jobs.py" }],
    selected_repo_paths: ["scripts/patchhub/app_api_jobs.py"],
    selected_entry_ids: ["entry_1"],
    can_execute: false,
    helper: { open: true, blockers: ["dirty overlap"], actions: ["refresh"] },
  },
);
const modal = document.getElementById("rollbackHelperModal");
process.stdout.write(JSON.stringify({
  hidden: modal.classList.contains("hidden"),
  ariaHidden: modal["aria-hidden"] || null,
  title: document.getElementById("rollbackHelperTitle").textContent || "",
}));
"""
    )
    result = _run_node(script)
    assert result == {
        "hidden": False,
        "ariaHidden": "false",
        "title": "Rollback blockers",
    }


def test_subset_picker_uses_shared_modal_view() -> None:
    script = (
        _prelude()
        + """
document.getElementById("mode").value = "rollback";
document.getElementById("targetRepo").value = "patchhub";
window.PH.register("modal_stub", {
  openZipSubsetModalView(model) { global.__subsetModal = model; },
  closeZipSubsetModalView() { global.__subsetClosed = true; },
});
window.PH.call(
  "rollbackApplyState",
  {
    job_id: "job-source-390-subset",
    issue_id: "390",
    commit_summary: "Subset source",
    effective_runner_target_repo: "patchhub",
  },
  {
    scope_kind: "full",
    selected_entry_count: 2,
    selected_entries: [
      {
        entry_id: "entry_1",
        label: "scripts/patchhub/app_api_jobs.py",
        selection_paths: ["scripts/patchhub/app_api_jobs.py"],
      },
      {
        entry_id: "entry_2",
        label: "scripts/patchhub/job_record_lookup.py",
        selection_paths: ["scripts/patchhub/job_record_lookup.py"],
      }
    ],
    selected_repo_paths: [
      "scripts/patchhub/app_api_jobs.py",
      "scripts/patchhub/job_record_lookup.py"
    ],
    selected_entry_ids: ["entry_1", "entry_2"],
    can_execute: true,
    helper: { open: false },
  },
);
window.PH.call("rollbackOpenSubsetPicker");
process.stdout.write(JSON.stringify({
  title: global.__subsetModal.title,
  subtitle: global.__subsetModal.subtitle,
  rowCount: global.__subsetModal.rows.length,
  firstRow: global.__subsetModal.rows[0].repo_path,
}));
"""
    )
    result = _run_node(script)
    assert result == {
        "title": "Select rollback scope",
        "subtitle": "Authoritative source scope of selected job",
        "rowCount": 2,
        "firstRow": "scripts/patchhub/app_api_jobs.py",
    }


def test_template_removes_redundant_rollback_buttons_and_uses_subset_strip() -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert 'id="rollbackUseFullBtn"' not in template
    assert 'id="rollbackChooseSubsetBtn"' not in template
    assert 'id="rollbackHelperBtn"' not in template
    assert 'id="rollbackSubsetStrip"' in template
