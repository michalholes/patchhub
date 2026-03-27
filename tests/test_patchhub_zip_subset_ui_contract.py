from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _node_prelude(*script_paths: Path) -> str:
    src_lines = []
    for idx, path in enumerate(script_paths):
        src_lines.append(f'const src{idx} = fs.readFileSync({json.dumps(str(path))}, "utf8");')
    run_lines = []
    for idx, path in enumerate(script_paths):
        run_lines.append(f"vm.runInThisContext(src{idx}, {{ filename: {json.dumps(str(path))} }});")
    return (
        """
import fs from "fs";
import vm from "vm";
const elements = new Map();
const registry = new Map();
const documentListeners = new Map();
function makeClassList() {
  const items = new Set();
  return {
    add: (...names) => names.forEach((name) => items.add(String(name))),
    remove: (...names) => names.forEach((name) => items.delete(String(name))),
    contains: (name) => items.has(String(name)),
  };
}
function makeNode(id) {
  const node = Object.assign(new global.HTMLElement(), {
    id,
    innerHTML: "",
    textContent: "",
    value: "",
    disabled: false,
    style: {},
    title: "",
    dataset: {},
    tabIndex: 0,
    classList: makeClassList(),
    parentElement: { classList: makeClassList() },
    _listeners: {},
    addEventListener(name, cb) {
      if (!this._listeners[name]) this._listeners[name] = [];
      this._listeners[name].push(cb);
    },
    removeEventListener() {},
    appendChild() {},
    setAttribute(name, value) { this[name] = String(value); },
    removeAttribute(name) { delete this[name]; },
    focus() {},
  });
  node.closest = () => null;
  return node;
}
global.HTMLElement = function HTMLElement() {};
global.window = { AMP_PATCHHUB_UI: {}, PH: {
  register(name, exports) { registry.set(String(name), exports || {}); },
  call(name, ...args) {
    for (const exports of [...registry.values()].reverse()) {
      if (exports && typeof exports[name] === "function") return exports[name](...args);
    }
    return null;
  },
  has(name) {
    for (const exports of [...registry.values()].reverse()) {
      if (exports && typeof exports[name] === "function") return true;
    }
    return false;
  },
}, __ph_patch_load_seq: 0, __uiStatus: [] };
global.document = {
  getElementById(id) {
    const key = String(id);
    if (!elements.has(key)) elements.set(key, makeNode(key));
    return elements.get(key);
  },
  addEventListener(name, cb) {
    const key = String(name);
    if (!documentListeners.has(key)) documentListeners.set(key, []);
    documentListeners.get(key).push(cb);
  },
};
global.__dispatchDocumentEvent = (name, event) => {
  const items = documentListeners.get(String(name)) || [];
  for (const cb of items) cb(event || {});
};
global.cfg = {
  targeting: { zip_target_prefill_enabled: true },
  autofill: { fill_patch_path: true, fill_issue_id: true, fill_commit_message: true },
};
global.dirty = { issueId: false, commitMsg: false, patchPath: false, targetRepo: false };
global.el = (id) => document.getElementById(id);
global.normalizePatchPath = (value) => String(value || "").trim();
global.getRawCommand = () => String(document.getElementById("rawCommand").value || "").trim();
global.setUiStatus = (msg) => window.__uiStatus.push(String(msg || ""));
global.selectedJobId = "";
global.suppressIdleOutput = false;
global.AMP_UI = { saveLiveJobId() {} };
global.setPre = () => {};
window.PH.register("stub", {
  validateAndPreview() {
    global.__validated = (global.__validated || 0) + 1;
    return true;
  },
  shouldOverwriteField(fieldKey, node) {
    if (fieldKey === "targetRepo") return !dirty.targetRepo;
    return String(node.value || "").trim() === "" || !dirty[fieldKey];
  },
  clearGateOverrides() { global.__gateCleared = (global.__gateCleared || 0) + 1; },
  clearPmValidationPayload() { global.__pmClears = (global.__pmClears || 0) + 1; },
  setPmValidationPayload(payload) { global.__pmPayload = payload; },
  closeZipSubsetModalView() {},
  openLiveStream() {},
});
"""
        + "\n".join(src_lines)
        + "\n"
        + "\n".join(run_lines)
    )


def _zip_subset_head_markup(html: str) -> str:
    match = re.search(
        r'<div class="zip-subset-list-head">(?P<head>.*?)</div>\s*'
        r'<div id="zipSubsetModalList"',
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group("head")


def test_main_ui_contains_zip_subset_and_progress_applied_hooks() -> None:
    html = (REPO_ROOT / "scripts" / "patchhub" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="zipSubsetStrip"' in html
    assert 'id="zipSubsetModal"' in html
    assert 'id="progressApplied"' in html
    assert 'id="zipSubsetModalTitle"' in html
    assert 'id="zipSubsetModalSubtitle"' in html
    assert 'id="zipSubsetSelectionCount"' in html
    assert 'id="zipSubsetApplyBtn"' in html
    head = _zip_subset_head_markup(html)
    assert ">patch<" not in head
    assert ">Repo path<" in head


def test_app_boot_sequence_loads_zip_subset_modules() -> None:
    app_js = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js").read_text(encoding="utf-8")
    assert "/static/app_part_zip_subset_modal.js" in app_js
    assert "/static/app_part_zip_subset.js" in app_js


def test_zip_subset_modal_is_hidden_by_css_specificity_rule() -> None:
    css = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".modal-backdrop.hidden" in css
    assert "display: none;" in css


def test_zip_subset_modal_uses_patchhub_blue_surface() -> None:
    css = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app.css").read_text(encoding="utf-8")
    assert "background: #121f3b;" in css
    assert "background: #0f1c33;" in css
    assert "background: #141414;" not in css


def test_zip_subset_runtime_exports_match_queue_upload_calls() -> None:
    subset_js = (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    ).read_text(encoding="utf-8")
    queue_js = (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_queue_upload.js"
    ).read_text(encoding="utf-8")
    for capability in [
        "syncZipSubsetUiFromInputs",
        "applyZipSubsetPreview",
        "getZipSubsetValidationState",
        "getZipSubsetEnqueuePayload",
    ]:
        assert capability in queue_js
        assert capability in subset_js


def test_zip_subset_preview_omits_metadata_for_original_zip() -> None:
    subset_js = (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    ).read_text(encoding="utf-8")
    assert "if (selected.length >= total)" in subset_js
    assert "delete preview.zip_subset;" in subset_js
    assert 'effective_patch_kind: "derived_subset_pending"' in subset_js


def test_zip_subset_modal_contract_matches_approved_layout_copy() -> None:
    subset_js = (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    ).read_text(encoding="utf-8")
    html = (REPO_ROOT / "scripts" / "patchhub" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "Select target files (" in subset_js
    assert "Contents of " in subset_js
    assert "All " in subset_js
    assert " selected" in subset_js
    assert 'id="zipSubsetApplyBtn"' in html
    assert "Cancel" in html
    assert "Apply" in html


def test_zip_subset_manual_same_path_reload_invalidates_cache_and_ignores_stale_response() -> None:
    subset_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    autofill_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_autofill_header.js"
    script = (
        _node_prelude(autofill_js, subset_js)
        + """
const pending = [];
global.apiGet = (path) => new Promise((resolve) => { pending.push({ path, resolve }); });
document.getElementById("mode").value = "patch";
document.getElementById("patchPath").value = "patches/issue_400_v1.zip";
document.getElementById("rawCommand").value = "stale raw";
document.getElementById("targetRepo").value = "patchhub";
dirty.patchPath = true;
window.PH.call("syncZipSubsetUiFromInputs");
document.getElementById("rawCommand").value = "stale raw again";
dirty.patchPath = true;
window.PH.call("syncZipSubsetUiFromInputs");
pending[0].resolve({
  ok: true,
  manifest: { selectable: true, patch_entry_count: 1, entries: [] },
  pm_validation: { ok: true },
  derived_target_repo: "audiomason2",
});
await Promise.resolve();
await Promise.resolve();
pending[1].resolve({
  ok: true,
  manifest: { selectable: true, patch_entry_count: 2, entries: [] },
  pm_validation: { ok: true, second: true },
  derived_target_repo: "patchhub",
});
await Promise.resolve();
await Promise.resolve();
process.stdout.write(JSON.stringify({
  requestCount: pending.length,
  targetRepo: document.getElementById("targetRepo").value,
  rawCommand: document.getElementById("rawCommand").value,
  patchLoadSeq: window.__ph_patch_load_seq,
  pmPayload: global.__pmPayload,
}));
"""
    )
    result = _run_node(script)
    assert result["requestCount"] == 2
    assert result["targetRepo"] == "patchhub"
    assert result["rawCommand"] == ""
    assert result["patchLoadSeq"] == 2
    assert result["pmPayload"] == {"ok": True, "second": True}


def test_enqueue_raw_command_uses_last_parsed_mode_in_request_body() -> None:
    queue_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_queue_upload.js"
    script = (
        _node_prelude(queue_js)
        + """
global.pushApiStatus = (payload) => {
  if (payload && payload.ok === false && payload.error) {
    global.__uiError = String(payload.error || "");
  }
};
global.setUiError = (msg) => { global.__uiError = String(msg || ""); };
global.apiPost = (_path, body) => {
  global.__postedBody = body;
  return Promise.resolve({ ok: false, error: "stop" });
};
document.getElementById("mode").value = "patch";
document.getElementById("rawCommand").value = 'python3 scripts/am_patch.py -f "Finalize"';
global.lastParsedRaw = document.getElementById("rawCommand").value;
global.lastParsed = { parsed: { mode: "finalize_live" } };
global.parseInFlight = false;
enqueue();
await Promise.resolve();
await Promise.resolve();
process.stdout.write(JSON.stringify({
  mode: global.__postedBody && global.__postedBody.mode,
  uiError: global.__uiError || "",
}));
"""
    )
    result = _run_node(script)
    assert result["mode"] == "finalize_live"
    assert result["uiError"] == "stop"


def test_enqueue_failed_request_logs_single_error_line() -> None:
    queue_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_queue_upload.js"
    script = (
        _node_prelude(queue_js)
        + """
global.__lines = [];
global.pushApiStatus = (payload) => {
  if (payload && payload.ok === false && payload.error) {
    global.__lines.push("ERROR: " + String(payload.error || ""));
  }
};
global.setUiError = (msg) => {
  global.__lines.push("ERROR: " + String(msg || ""));
};
global.apiPost = (_path, _body) => Promise.resolve({ ok: false, error: "bad json" });
document.getElementById("mode").value = "patch";
document.getElementById("issueId").value = "348";
document.getElementById("commitMsg").value = "fix enqueue";
document.getElementById("patchPath").value = "patches/issue_348_v1.zip";
enqueue();
await Promise.resolve();
await Promise.resolve();
process.stdout.write(JSON.stringify({ lines: global.__lines }));
"""
    )
    result = _run_node(script)
    assert result["lines"] == ["ERROR: bad json"]


def test_zip_subset_retry_fetches_new_manifest_after_error() -> None:
    subset_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    script = (
        _node_prelude(subset_js)
        + """
const pending = [];
global.apiGet = (path) => new Promise((resolve) => { pending.push({ path, resolve }); });
document.getElementById("mode").value = "patch";
document.getElementById("patchPath").value = "patches/issue_350_v1.zip";
window.PH.call("syncZipSubsetUiFromInputs");
pending[0].resolve({ ok: false, error: "manifest failed" });
await Promise.resolve();
await Promise.resolve();
const strip = document.getElementById("zipSubsetStrip");
strip.closest = (selector) => (selector === "#zipSubsetStrip" ? strip : null);
__dispatchDocumentEvent("click", { target: strip });
pending[1].resolve({
  ok: true,
  manifest: {
    selectable: true,
    patch_entry_count: 2,
    entries: [
      { zip_member: "patches/per_file/a.patch", repo_path: "a", selectable: true },
      { zip_member: "patches/per_file/b.patch", repo_path: "b", selectable: true },
    ],
  },
  pm_validation: { ok: true, retried: true },
});
await Promise.resolve();
await Promise.resolve();
process.stdout.write(JSON.stringify({
  requestCount: pending.length,
  actions: pending.map((item) => item.path),
  stripAction: strip.dataset.action || "",
  stripHtml: strip.innerHTML,
  subsetState: window.PH.call("getZipSubsetValidationState"),
  pmPayload: global.__pmPayload,
}));
"""
    )
    result = _run_node(script)
    assert result["requestCount"] == 2
    assert result["actions"] == [
        "/api/patches/zip_manifest?path=patches%2Fissue_350_v1.zip",
        "/api/patches/zip_manifest?path=patches%2Fissue_350_v1.zip",
    ]
    assert result["stripAction"] == "open"
    assert "Loading target files..." not in result["stripHtml"]
    assert result["subsetState"] == {"ok": True, "hint": ""}
    assert result["pmPayload"] == {"ok": True, "retried": True}


def test_polling_same_path_new_content_refetches_manifest_and_replaces_state() -> None:
    autofill_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_autofill_header.js"
    subset_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    script = (
        _node_prelude(autofill_js, subset_js)
        + """
const pollPending = [];
const manifestPending = [];
global.latestToken = "";
global.lastAutofillClearedToken = "";
global.pushApiStatus = () => {};
global.setUiError = (msg) => { global.__uiError = String(msg || ""); };
cfg.autofill.enabled = true;
window.PH.register("test_validate", {
  validateAndPreview() {
    return window.PH.call("syncZipSubsetUiFromInputs");
  },
});
global.apiGetETag = (_name, _path) => new Promise((resolve) => { pollPending.push(resolve); });
global.apiGet = (path) => new Promise((resolve) => { manifestPending.push({ path, resolve }); });
document.getElementById("mode").value = "patch";
pollLatestPatchOnce();
pollPending[0]({
  ok: true,
  found: true,
  token: "tok-1",
  stored_rel_path: "patches/issue_350_v1.zip",
  derived_issue: "350",
  derived_commit_message: "first load",
});
await Promise.resolve();
await Promise.resolve();
manifestPending[0].resolve({
  ok: true,
  manifest: { selectable: true, patch_entry_count: 1, entries: [] },
  pm_validation: { ok: true, first: true },
  derived_target_repo: "patchhub",
});
await Promise.resolve();
await Promise.resolve();
pollLatestPatchOnce();
pollPending[1]({
  ok: true,
  found: true,
  token: "tok-2",
  stored_rel_path: "patches/issue_350_v1.zip",
  derived_issue: "350",
  derived_commit_message: "second load",
});
await Promise.resolve();
await Promise.resolve();
manifestPending[1].resolve({
  ok: true,
  manifest: { selectable: true, patch_entry_count: 2, entries: [] },
  pm_validation: { ok: true, second: true },
  derived_target_repo: "audiomason2",
});
await Promise.resolve();
await Promise.resolve();
process.stdout.write(JSON.stringify({
  manifestRequestCount: manifestPending.length,
  manifestPaths: manifestPending.map((item) => item.path),
  patchLoadSeq: window.__ph_patch_load_seq,
  patchPath: document.getElementById("patchPath").value,
  commitMsg: document.getElementById("commitMsg").value,
  targetRepo: document.getElementById("targetRepo").value,
  pmPayload: global.__pmPayload,
}));
"""
    )
    result = _run_node(script)
    assert result["manifestRequestCount"] == 2
    assert result["manifestPaths"] == [
        "/api/patches/zip_manifest?path=patches%2Fissue_350_v1.zip",
        "/api/patches/zip_manifest?path=patches%2Fissue_350_v1.zip",
    ]
    assert result["patchLoadSeq"] == 2
    assert result["patchPath"] == "patches/issue_350_v1.zip"
    assert result["commitMsg"] == "second load"
    assert result["targetRepo"] == "audiomason2"
    assert result["pmPayload"] == {"ok": True, "second": True}


def test_start_after_autofill_loaded_patch_enqueues_once() -> None:
    autofill_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_autofill_header.js"
    subset_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    queue_js = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_queue_upload.js"
    script = (
        _node_prelude(autofill_js, subset_js, queue_js)
        + """
const pollPending = [];
const manifestPending = [];
global.latestToken = "";
global.lastAutofillClearedToken = "";
global.pushApiStatus = () => {};
global.setUiError = (msg) => { global.__uiError = String(msg || ""); };
global.setInfoPoolHint = () => {};
global.tickMissingPatchClear = () => {};
global.computeCanonicalPreview = () => [];
global.apiGetETag = (_name, _path) => new Promise((resolve) => { pollPending.push(resolve); });
global.apiGet = (path) => new Promise((resolve) => { manifestPending.push({ path, resolve }); });
global.apiPost = (_path, body) => {
  global.__postCalls = (global.__postCalls || 0) + 1;
  global.__postedBody = body;
  return Promise.resolve({ ok: true, job_id: "job-1" });
};
cfg.autofill.enabled = true;
cfg.autofill.overwrite_policy = "only_if_empty";
document.getElementById("mode").value = "patch";
pollLatestPatchOnce();
pollPending[0]({
  ok: true,
  found: true,
  token: "tok-1",
  stored_rel_path: "patches/issue_350_v1.zip",
  derived_issue: "350",
  derived_commit_message: "ready to start",
});
await Promise.resolve();
await Promise.resolve();
manifestPending[0].resolve({
  ok: true,
  manifest: {
    selectable: true,
    patch_entry_count: 1,
    entries: [
      { zip_member: "patches/per_file/app.patch", repo_path: "app", selectable: true },
    ],
  },
  pm_validation: { ok: true },
  derived_target_repo: "patchhub",
});
await Promise.resolve();
await Promise.resolve();
const enqueueBtn = document.getElementById("enqueueBtn");
enqueue();
await Promise.resolve();
await Promise.resolve();
process.stdout.write(JSON.stringify({
  disabled: enqueueBtn.disabled,
  postCalls: global.__postCalls || 0,
  postedBody: global.__postedBody,
  selectedJobId: global.selectedJobId,
}));
"""
    )
    result = _run_node(script)
    assert result["disabled"] is False
    assert result["postCalls"] == 1
    assert result["postedBody"] == {
        "mode": "patch",
        "raw_command": "",
        "issue_id": "350",
        "commit_message": "ready to start",
        "patch_path": "patches/issue_350_v1.zip",
        "target_repo": "patchhub",
    }
    assert result["selectedJobId"] == "job-1"
