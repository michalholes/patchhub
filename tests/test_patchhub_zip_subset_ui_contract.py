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
function makeClassList() {
  const items = new Set();
  return {
    add: (...names) => names.forEach((name) => items.add(String(name))),
    remove: (...names) => names.forEach((name) => items.delete(String(name))),
    contains: (name) => items.has(String(name)),
  };
}
function makeNode(id) {
  return {
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
  };
}
global.window = { AMP_PATCHHUB_UI: {}, PH: {
  register(name, exports) { registry.set(String(name), exports || {}); },
  call(name, ...args) {
    for (const exports of registry.values()) {
      if (exports && typeof exports[name] === "function") return exports[name](...args);
    }
    return null;
  },
  has(name) {
    for (const exports of registry.values()) {
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
  addEventListener() {},
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
global.pushApiStatus = () => {};
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
