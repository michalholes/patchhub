from __future__ import annotations

import json
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
    toggle: (name, force) => {
      const key = String(name);
      const enabled = force === undefined ? !items.has(key) : !!force;
      if (enabled) items.add(key);
      else items.delete(key);
      return enabled;
    },
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
    parentElement: { classList: makeClassList() },
    classList: makeClassList(),
    _listeners: {},
    addEventListener(name, cb) {
      if (!this._listeners[name]) this._listeners[name] = [];
      this._listeners[name].push(cb);
    },
    removeEventListener() {},
    appendChild() {},
    focus() {},
    setAttribute(name, value) { this[name] = String(value); },
    getAttribute(name) { return this[name] || null; },
    dispatch(name, payload) {
      const event = payload || { target: this };
      (this._listeners[name] || []).forEach((cb) => cb(event));
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}
global.window = {
  AMP_PATCHHUB_UI: {
    saveLiveJobId() {},
    openLiveStream() {},
    closeLiveStream() {},
  },
  PH: {
    register(name, exports) {
      registry.set(String(name), exports || {});
    },
    call(name, ...args) {
      for (const exports of registry.values()) {
        if (exports && typeof exports[name] === "function") {
          return exports[name](...args);
        }
      }
      return null;
    },
    has(name) {
      for (const exports of registry.values()) {
        if (exports && typeof exports[name] === "function") return true;
      }
      return false;
    },
  },
  __uiStatus: [],
  __uiErrors: [],
};
global.document = {
  hidden: false,
  getElementById(id) {
    const key = String(id);
    if (!elements.has(key)) elements.set(key, makeNode(key));
    return elements.get(key);
  },
};
global.localStorage = {
  getItem() { return null; },
  setItem() {},
};
global.cfg = {
  runner: { command: ["python3", "scripts/am_patch.py"] },
  ui: { idle_auto_select_last_job: false },
  server: { host: "127.0.0.1", port: 8080 },
};
global.selectedJobId = "";
global.suppressIdleOutput = false;
global.autoRefreshTimer = null;
global.idleSigs = { jobs: "", runs: "", workspaces: "", hdr: "", snapshot: "" };
global.idleNextDueMs = 0;
global.idleBackoffIdx = 0;
global.IDLE_BACKOFF_MS = [1000, 2000];
global.workspacesCache = [];
global.dirty = { issueId: false, commitMsg: false, patchPath: false };
global.confirm = () => true;
global.clearParsedState = () => { global.__parsedCleared = true; };
global.setParseHint = (msg) => { global.__parseHint = String(msg || ""); };
global.setUiStatus = (msg) => window.__uiStatus.push(String(msg || ""));
global.setUiError = (msg) => window.__uiErrors.push(String(msg || ""));
global.setPre = () => {};
global.normalizePatchPath = (value) => String(value || "").trim();
global.escapeHtml = (s) => String(s || "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/\"/g, "&quot;")
  .replace(/'/g, "&#39;");
global.formatLocalTime = (value) => String(value || "");
global.el = (id) => document.getElementById(id);
global.apiGetETag = () => Promise.resolve({ ok: true, unchanged: true });
global.refreshFs = () => {};
global.setFsHint = () => {};
global.fetch = () => Promise.resolve({
  status: 200,
  text: () => Promise.resolve(JSON.stringify({ ok: true })),
});
window.PH.register("stub", {
  validateAndPreview() {
    global.__validated = {
      mode: document.getElementById("mode").value,
      issueId: document.getElementById("issueId").value,
      commitMsg: document.getElementById("commitMsg").value,
      patchPath: document.getElementById("patchPath").value,
    };
    return true;
  },
  renderActiveJob() {},
  getLiveJobId() { return ""; },
  hasTrackedActiveJob() { return false; },
  openLiveStream() {},
  closeLiveStream() {},
  loadLiveJobId() { return null; },
  jobSummaryDurationSeconds() { return ""; },
  renderRunsFromResponse() {},
  renderWorkspacesFromResponse() {},
  renderHeaderFromSummary() {},
  clearGateOverrides() {},
});
"""
        + "\n".join(src_lines)
        + "\n"
        + "\n".join(run_lines)
    )


def test_workspace_finalize_prepares_form_without_enqueue() -> None:
    script_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_workspaces.js"
    script = (
        _node_prelude(script_path)
        + """
const workspacesList = document.getElementById("workspacesList");
const finalizeBtn = document.getElementById("fakeFinalize");
const openBtn = document.getElementById("fakeOpen");
const deleteBtn = document.getElementById("fakeDelete");
const itemNode = {
  getAttribute(name) {
    if (name === "data-idx") return "0";
    return null;
  },
  querySelector(selector) {
    if (selector === ".wsFinalize") return finalizeBtn;
    if (selector === ".wsOpen") return openBtn;
    if (selector === ".wsDelete") return deleteBtn;
    return null;
  },
};
workspacesList.querySelectorAll = () => [itemNode];
window.PH.register("recorder", {
  enqueue() {
    global.__enqueueCalls = (global.__enqueueCalls || 0) + 1;
  },
});
document.getElementById("mode").value = "patch";
document.getElementById("issueId").value = "";
document.getElementById("commitMsg").value = "abc";
document.getElementById("patchPath").value = "patches/x.zip";
document.getElementById("rawCommand").value = "raw value";
renderWorkspacesFromResponse({
  items: [{ issue_id: 310, workspace_rel_path: "patches/ws_310", state: "DIRTY" }],
});
finalizeBtn.dispatch("click");
process.stdout.write(JSON.stringify({
  mode: document.getElementById("mode").value,
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  rawCommand: document.getElementById("rawCommand").value,
  enqueueCalls: global.__enqueueCalls || 0,
  validated: global.__validated,
  uiStatus: window.__uiStatus,
}));
"""
    )
    result = _run_node(script)
    assert result["mode"] == "finalize_workspace"
    assert result["issueId"] == "310"
    assert result["commitMsg"] == ""
    assert result["patchPath"] == ""
    assert result["rawCommand"] == ""
    assert result["enqueueCalls"] == 0
    assert result["validated"]["mode"] == "finalize_workspace"
    assert result["uiStatus"][-1] == "finalize_workspace: prepared form for issue_id=310"


def test_rerun_latest_helper_uses_job_detail_authority() -> None:
    script_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
    script = (
        _node_prelude(script_path)
        + """
global.apiGet = (path) => {
  if (path === "/api/jobs") {
    return Promise.resolve({
      ok: true,
      jobs: [
        {
          job_id: "job-eligible",
          mode: "patch",
          issue_id: "311",
          commit_summary: "Spec update",
          created_utc: "2026-03-13T10:00:00Z",
          status: "success",
          patch_basename: "issue_311_v1.zip",
        },
      ],
    });
  }
  if (path === "/api/jobs/job-eligible") {
    return Promise.resolve({
      ok: true,
      job: {
        job_id: "job-eligible",
        mode: "patch",
        issue_id: "311",
        commit_message: "Spec update for rerun latest authority",
        effective_patch_path: "patches/issue_311_v1.zip",
        canonical_command: [
          "python3",
          "scripts/am_patch.py",
          "311",
          "Spec update for rerun latest authority",
          "patches/issue_311_v1.zip",
        ],
      },
    });
  }
  if (path === "/api/fs/stat?path=issue_311_v1.zip") {
    return Promise.resolve({ ok: true, exists: true });
  }
  return Promise.resolve({ ok: false, error: "unexpected path: " + path });
};
document.getElementById("mode").value = "rerun_latest";
renderJobsFromResponse({
  jobs: [
    {
      job_id: "job-eligible",
      mode: "patch",
      issue_id: "311",
      commit_summary: "Spec update",
      created_utc: "2026-03-13T10:00:00Z",
      status: "success",
      patch_basename: "issue_311_v1.zip",
    },
  ],
});
await prepareRerunLatestFromLatestJob();
process.stdout.write(JSON.stringify({
  mode: document.getElementById("mode").value,
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  jobsHtml: document.getElementById("jobsList").innerHTML,
  validated: global.__validated,
  uiStatus: window.__uiStatus,
  uiErrors: window.__uiErrors,
}));
"""
    )
    result = _run_node(script)
    assert result["mode"] == "rerun_latest"
    assert result["issueId"] == "311"
    assert result["commitMsg"] == "Spec update for rerun latest authority"
    assert result["patchPath"] == "patches/issue_311_v1.zip"
    assert 'data-rerun-jobid="job-eligible"' in result["jobsHtml"]
    assert "Use for -l" in result["jobsHtml"]
    assert result["validated"]["patchPath"] == "patches/issue_311_v1.zip"
    assert result["uiErrors"] == []
    assert result["uiStatus"][-1] == (
        "rerun_latest: prepared form from latest usable job_id=job-eligible"
    )


def test_rerun_latest_helper_skips_first_detail_ineligible_job() -> None:
    script_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
    script = (
        _node_prelude(script_path)
        + """
global.apiGet = (path) => {
  if (path === "/api/jobs") {
    return Promise.resolve({
      ok: true,
      jobs: [
        {
          job_id: "job-invalid",
          mode: "patch",
          issue_id: "312",
          commit_summary: "Invalid first",
          created_utc: "2026-03-13T12:00:00Z",
          status: "success",
          patch_basename: "issue_312_v5.zip",
        },
        {
          job_id: "job-valid",
          mode: "patch",
          issue_id: "311",
          commit_summary: "Valid second",
          created_utc: "2026-03-13T11:00:00Z",
          status: "success",
          patch_basename: "issue_311_v1.zip",
        },
      ],
    });
  }
  if (path === "/api/jobs/job-invalid") {
    return Promise.resolve({
      ok: true,
      job: {
        job_id: "job-invalid",
        mode: "patch",
        issue_id: "312",
        commit_message: "Invalid missing patch",
        effective_patch_path: "patches/issue_312_v5.zip",
        canonical_command: [
          "python3",
          "scripts/am_patch.py",
          "312",
          "Invalid missing patch",
          "patches/issue_312_v5.zip",
        ],
      },
    });
  }
  if (path === "/api/jobs/job-valid") {
    return Promise.resolve({
      ok: true,
      job: {
        job_id: "job-valid",
        mode: "patch",
        issue_id: "311",
        commit_message: "Valid second job",
        effective_patch_path: "patches/issue_311_v1.zip",
        canonical_command: [
          "python3",
          "scripts/am_patch.py",
          "311",
          "Valid second job",
          "patches/issue_311_v1.zip",
        ],
      },
    });
  }
  if (path === "/api/fs/stat?path=issue_312_v5.zip") {
    return Promise.resolve({ ok: true, exists: false });
  }
  if (path === "/api/fs/stat?path=issue_311_v1.zip") {
    return Promise.resolve({ ok: true, exists: true });
  }
  return Promise.resolve({ ok: false, error: "unexpected path: " + path });
};
document.getElementById("mode").value = "rerun_latest";
document.getElementById("issueId").value = "stale";
document.getElementById("commitMsg").value = "stale";
document.getElementById("patchPath").value = "stale";
await prepareRerunLatestFromLatestJob();
process.stdout.write(JSON.stringify({
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  uiStatus: window.__uiStatus,
  uiErrors: window.__uiErrors,
}));
"""
    )
    result = _run_node(script)
    assert result["issueId"] == "311"
    assert result["commitMsg"] == "Valid second job"
    assert result["patchPath"] == "patches/issue_311_v1.zip"
    assert result["uiErrors"] == []
    assert result["uiStatus"][-1] == (
        "rerun_latest: prepared form from latest usable job_id=job-valid"
    )


def test_progress_ui_keeps_active_controls_for_tracked_fallback_and_cancel_409() -> None:
    script_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "patchhub_progress_ui.js"
    script = (
        _node_prelude(script_path)
        + """
window.PH.register("progress_stub", {
  getTrackedActiveJob() {
    return {
      job_id: "job-fallback",
      status: "running",
      mode: "patch",
      issue_id: "310",
    };
  },
  getTrackedActiveJobId() {
    return "job-fallback";
  },
});
global.refreshJobs = () => {};
global.fetch = (path) => Promise.resolve({
  status: 409,
  text: () => Promise.resolve(JSON.stringify({ ok: false, error: "Cannot cancel" })),
});
window.AMP_PATCHHUB_UI.renderActiveJob([]);
const fallbackHtml = document.getElementById("activeJob").innerHTML;
const cancelBtn = document.getElementById("cancelActive");
await cancelBtn._listeners.click[0]({ target: cancelBtn });
await new Promise((resolve) => setTimeout(resolve, 0));
process.stdout.write(JSON.stringify({
  fallbackHtml,
  uiErrors: window.__uiErrors,
}));
"""
    )
    result = _run_node(script)
    assert 'id="cancelActive"' in result["fallbackHtml"]
    assert 'id="hardStopActive"' in result["fallbackHtml"]
    assert result["uiErrors"][-1] == "Cannot cancel"


def test_source_wires_rerun_latest_prepare_and_removes_workspace_auto_enqueue() -> None:
    jobs_src = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js").read_text(
        encoding="utf-8"
    )
    wire_src = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_wire_init.js").read_text(
        encoding="utf-8"
    )
    workspaces_src = (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_workspaces.js"
    ).read_text(encoding="utf-8")

    assert "Use for -l" in jobs_src
    assert 'phCall("prepareRerunLatestFromLatestJob")' in wire_src
    assert 'phCall("prepareRerunLatestFromJobId"' in wire_src
    assert "clearOnFailure: false" in wire_src
    assert "out.canonical_argv = out.canonical_argv.concat(gateArgv);" not in (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_gate_options.js"
    ).read_text(encoding="utf-8")
    finalize_handler = workspaces_src.split('finBtn.addEventListener("click", () => {', 1)[1]
    finalize_handler = finalize_handler.split("});", 1)[0]
    assert 'phCall("enqueue")' not in finalize_handler
    assert "clearParsedState();" in finalize_handler


def test_rerun_latest_helper_clears_form_when_no_detail_eligible_job() -> None:
    script_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
    script = (
        _node_prelude(script_path)
        + """
global.apiGet = (path) => {
  if (path === "/api/jobs") {
    return Promise.resolve({
      ok: true,
      jobs: [
        {
          job_id: "job-invalid",
          mode: "patch",
          issue_id: "312",
          commit_summary: "Invalid only",
          created_utc: "2026-03-13T12:00:00Z",
          status: "success",
          patch_basename: "issue_312_v5.zip",
        },
      ],
    });
  }
  if (path === "/api/jobs/job-invalid") {
    return Promise.resolve({
      ok: true,
      job: {
        job_id: "job-invalid",
        mode: "patch",
        issue_id: "312",
        commit_message: "Invalid missing patch",
        effective_patch_path: "patches/issue_312_v5.zip",
        canonical_command: [
          "python3",
          "scripts/am_patch.py",
          "312",
          "Invalid missing patch",
          "patches/issue_312_v5.zip",
        ],
      },
    });
  }
  if (path === "/api/fs/stat?path=issue_312_v5.zip") {
    return Promise.resolve({ ok: true, exists: false });
  }
  return Promise.resolve({ ok: false, error: "unexpected path: " + path });
};
document.getElementById("mode").value = "rerun_latest";
document.getElementById("issueId").value = "stale-issue";
document.getElementById("commitMsg").value = "stale-message";
document.getElementById("patchPath").value = "stale-patch";
await prepareRerunLatestFromLatestJob();
process.stdout.write(JSON.stringify({
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  uiStatus: window.__uiStatus,
  uiErrors: window.__uiErrors,
}));
"""
    )
    result = _run_node(script)
    assert result["issueId"] == ""
    assert result["commitMsg"] == ""
    assert result["patchPath"] == ""
    assert result["uiErrors"] == []
    assert result["uiStatus"][-1] == "rerun_latest: no usable previous job"


def test_rerun_latest_selected_job_invalid_leaves_form_unchanged_and_sets_error() -> None:
    script_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
    script = (
        _node_prelude(script_path)
        + """
global.apiGet = (path) => {
  if (path === "/api/jobs/job-invalid") {
    return Promise.resolve({
      ok: true,
      job: {
        job_id: "job-invalid",
        mode: "patch",
        issue_id: "312",
        commit_message: "Invalid missing patch",
        effective_patch_path: "patches/issue_312_v5.zip",
        canonical_command: [
          "python3",
          "scripts/am_patch.py",
          "312",
          "Invalid missing patch",
          "patches/issue_312_v5.zip",
        ],
      },
    });
  }
  if (path === "/api/fs/stat?path=issue_312_v5.zip") {
    return Promise.resolve({ ok: true, exists: false });
  }
  return Promise.resolve({ ok: false, error: "unexpected path: " + path });
};
document.getElementById("mode").value = "rerun_latest";
document.getElementById("issueId").value = "stale-issue";
document.getElementById("commitMsg").value = "stale-message";
document.getElementById("patchPath").value = "stale-patch";
await prepareRerunLatestFromJobId("job-invalid", {
  sourceLabel: "selected jobs item",
  clearOnFailure: false,
});
process.stdout.write(JSON.stringify({
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  uiStatus: window.__uiStatus,
  uiErrors: window.__uiErrors,
}));
"""
    )
    result = _run_node(script)
    assert result["issueId"] == "stale-issue"
    assert result["commitMsg"] == "stale-message"
    assert result["patchPath"] == "stale-patch"
    assert result["uiStatus"][-1] == (
        "rerun_latest: selected job is not usable for Start-form autofill"
    )
    assert result["uiErrors"][-1] == (
        "rerun_latest: selected job is not usable for Start-form autofill"
    )


def test_mode_change_to_rerun_latest_prepares_form_via_wire_buttons() -> None:
    jobs_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
    wire_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_wire_init.js"
    script = (
        _node_prelude(jobs_path, wire_path)
        + """
global.apiGet = (path) => {
  if (path === "/api/jobs") {
    return Promise.resolve({
      ok: true,
      jobs: [
        {
          job_id: "job-valid",
          mode: "patch",
          issue_id: "311",
          commit_summary: "Ready patch",
          created_utc: "2026-03-13T13:00:00Z",
          status: "success",
          patch_basename: "issue_311_v2.zip",
        },
      ],
    });
  }
  if (path === "/api/jobs/job-valid") {
    return Promise.resolve({
      ok: true,
      job: {
        job_id: "job-valid",
        mode: "patch",
        issue_id: "311",
        commit_message: "Ready patch",
        effective_patch_path: "patches/issue_311_v2.zip",
        canonical_command: [
          "python3",
          "scripts/am_patch.py",
          "311",
          "Ready patch",
          "patches/issue_311_v2.zip",
        ],
      },
    });
  }
  if (path === "/api/fs/stat?path=issue_311_v2.zip") {
    return Promise.resolve({ ok: true, exists: true });
  }
  return Promise.resolve({ ok: false, error: "unexpected path: " + path });
};
wireButtons();
document.getElementById("mode").value = "rerun_latest";
document.getElementById("mode").dispatch("change");
await new Promise((resolve) => setTimeout(resolve, 0));
await new Promise((resolve) => setTimeout(resolve, 0));
process.stdout.write(JSON.stringify({
  mode: document.getElementById("mode").value,
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  validated: global.__validated,
  uiStatus: window.__uiStatus,
  uiErrors: window.__uiErrors,
}));
"""
    )
    result = _run_node(script)
    assert result["mode"] == "rerun_latest"
    assert result["issueId"] == "311"
    assert result["commitMsg"] == "Ready patch"
    assert result["patchPath"] == "patches/issue_311_v2.zip"
    assert result["validated"]["mode"] == "rerun_latest"
    assert result["uiErrors"] == []
    assert result["uiStatus"][-1] == (
        "rerun_latest: prepared form from latest usable job_id=job-valid"
    )


def test_jobs_rerun_button_prepares_form_via_wire_buttons() -> None:
    jobs_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
    wire_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_wire_init.js"
    script = (
        _node_prelude(jobs_path, wire_path)
        + """
global.apiGet = (path) => {
  if (path === "/api/jobs/job-eligible") {
    return Promise.resolve({
      ok: true,
      job: {
        job_id: "job-eligible",
        mode: "patch",
        issue_id: "312",
        commit_message: "Chosen patch",
        effective_patch_path: "patches/issue_312_v3.zip",
        canonical_command: [
          "python3",
          "scripts/am_patch.py",
          "312",
          "Chosen patch",
          "patches/issue_312_v3.zip",
        ],
      },
    });
  }
  if (path === "/api/fs/stat?path=issue_312_v3.zip") {
    return Promise.resolve({ ok: true, exists: true });
  }
  return Promise.resolve({ ok: false, error: "unexpected path: " + path });
};
wireButtons();
const jobsList = document.getElementById("jobsList");
const button = {
  parentElement: jobsList,
  getAttribute(name) {
    if (name === "data-rerun-jobid") return "job-eligible";
    return null;
  },
};
jobsList.dispatch("click", { target: button });
await new Promise((resolve) => setTimeout(resolve, 0));
await new Promise((resolve) => setTimeout(resolve, 0));
process.stdout.write(JSON.stringify({
  mode: document.getElementById("mode").value,
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  validated: global.__validated,
  uiStatus: window.__uiStatus,
  uiErrors: window.__uiErrors,
}));
"""
    )
    result = _run_node(script)
    assert result["mode"] == "rerun_latest"
    assert result["issueId"] == "312"
    assert result["commitMsg"] == "Chosen patch"
    assert result["patchPath"] == "patches/issue_312_v3.zip"
    assert result["validated"]["mode"] == "rerun_latest"
    assert result["uiErrors"] == []
    assert result["uiStatus"][-1] == (
        "rerun_latest: prepared form from selected jobs item job_id=job-eligible"
    )
