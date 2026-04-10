from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JOBS_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
APP_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js"
INFO_POOL_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_info_pool.js"
AUTOFILL_HEADER_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_autofill_header.js"


def _run_node(script: str) -> dict[str, str]:
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
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)
    return {str(key): str(value) for key, value in data.items()}


def _prelude() -> str:
    jobs_path = json.dumps(str(JOBS_PATH))
    app_path = json.dumps(str(APP_PATH))
    return f"""
import fs from "fs";
import vm from "vm";
const jobsSrc = fs.readFileSync({jobs_path}, "utf8");
const appSrc = fs.readFileSync({app_path}, "utf8");
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
    _listeners: Object.create(null),
    addEventListener(name, cb) {{
      if (!this._listeners[name]) this._listeners[name] = [];
      this._listeners[name].push(cb);
    }},
    removeEventListener() {{}},
    appendChild() {{}},
    focus() {{}},
    setAttribute(name, value) {{ this[String(name)] = String(value); }},
    getAttribute(name) {{ return this[String(name)] || null; }},
    querySelectorAll() {{ return []; }},
    dispatchEvent() {{ return true; }},
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
  has(name) {{
    for (const exportsObj of registry.values()) {{
      if (exportsObj && typeof exportsObj[name] === "function") return true;
    }}
    return false;
  }},
}};
global.window = {{ PH: runtime, AMP_PATCHHUB_UI: {{ saveLiveJobId() {{}} }} }};
global.document = {{
  hidden: false,
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
global.cfg = {{
  runner: {{ command: ["python3", "scripts/am_patch.py"] }},
  ui: {{ idle_auto_select_last_job: false }},
  server: {{ host: "127.0.0.1", port: 8080 }},
}};
global.selectedJobId = "job-selected";
global.suppressIdleOutput = false;
global.autoRefreshTimer = null;
global.idleSigs = {{
  jobs: "",
  runs: "",
  patches: "",
  workspaces: "",
  hdr: "",
  snapshot: "",
  operator_info: "",
}};
global.idleNextDueMs = 0;
global.idleBackoffIdx = 0;
global.IDLE_BACKOFF_MS = [1000, 2000];
global.dirty = {{ issueId: false, commitMsg: false, patchPath: false, targetRepo: false }};
global.backendDegradedNote = "";
global.backendOperatorInfo = {{ cleanup_recent_status: [] }};
global.appPhRuntime = runtime;
global.UI_STATUS_LIMIT = 20;
global.degradedNotes = [];
global.uiStatusLines = [];
global.infoPoolHints = {{ upload: "", enqueue: "", fs: "", parse: "" }};
global.infoPoolHintSeq = {{ upload: 0, enqueue: 0, fs: 0, parse: 0 }};
global.infoPoolSeq = 0;
global.el = (id) => document.getElementById(id);
global.escapeHtml = (value) => String(value || "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/\"/g, "&quot;")
  .replace(/'/g, "&#39;");
global.setUiStatus = () => {{}};
global.setUiError = () => {{}};
global.setPre = () => {{}};
global.normalizePatchPath = (value) => String(value || "");
global.clearParsedState = () => {{}};
global.setParseHint = () => {{}};
global.apiGetETag = () => Promise.resolve({{ ok: true, jobs: [] }});
global.apiGet = () => Promise.resolve({{ ok: true, job: null }});
global.apiPost = () => Promise.resolve({{ ok: true }});
global.PH = runtime;
runtime.register("stub", {{
  getTrackedActiveJobId() {{ return ""; }},
  getVisibleDurationNowMs() {{ return 0; }},
  readVisibleRuntimeElapsedMs() {{ return 0; }},
  getTrackedActiveJob() {{ return null; }},
  formatVisibleDurationMs(ms) {{ return String(ms || ""); }},
  setVisibleDurationSurface() {{ return true; }},
  clearVisibleDurationSurface() {{ return true; }},
  syncProtectedRerunLatestLifecycleFromJobs() {{ return true; }},
  isProtectedRerunLatestLifecycleActive() {{ return false; }},
  clearProtectedRerunLatestLifecycle() {{ return true; }},
  isNonTerminalJobStatus(status) {{
    const s = String(status || "").trim().toLowerCase();
    return s === "running" || s === "queued";
  }},
  jobSummaryDurationSeconds() {{ return ""; }},
  renderActiveJob() {{ return true; }},
  loadLiveJobId() {{ return null; }},
  renderRunsFromResponse() {{ return true; }},
  renderPatchesFromResponse() {{ return true; }},
  renderWorkspacesFromResponse() {{ return true; }},
  renderHeaderFromSummary() {{ return true; }},
  refreshOverviewSnapshot() {{ return Promise.resolve({{ changed: false }}); }},
  getLiveJobId() {{ return ""; }},
  hasTrackedActiveJob() {{ return false; }},
  openLiveStream() {{ return true; }},
  closeLiveStream() {{ return true; }},
  validateAndPreview() {{ return true; }},
}});
vm.runInThisContext(appSrc, {{ filename: {app_path} }});
vm.runInThisContext(jobsSrc, {{ filename: {jobs_path} }});
const appPartJobs = registry.get("app_part_jobs");
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
"""


def _info_pool_prelude() -> str:
    info_pool_path = json.dumps(str(INFO_POOL_PATH))
    autofill_header_path = json.dumps(str(AUTOFILL_HEADER_PATH))
    return (
        _prelude()
        + f"""
const infoPoolSrc = fs.readFileSync({info_pool_path}, "utf8");
const autofillHeaderSrc = fs.readFileSync({autofill_header_path}, "utf8");
vm.runInThisContext(infoPoolSrc, {{ filename: {info_pool_path} }});
vm.runInThisContext(autofillHeaderSrc, {{ filename: {autofill_header_path} }});
runtime.register("info_pool_stub", {{
  getPmValidationSummary() {{ return ""; }},
  getPmValidationSnapshot() {{ return null; }},
}});
"""
    )


def test_jobs_list_selected_item_renders_origin_evidence() -> None:
    script = (
        _prelude()
        + """
global.apiGetETag = () => Promise.resolve({
  ok: true,
  jobs: [
    {
      job_id: 'job-selected',
      status: 'success',
      created_utc: '2026-03-25T09:15:00Z',
      issue_id: '381',
      commit_summary: 'Completed',
      patch_basename: 'issue_381_v1.zip',
      mode: 'patch',
    },
  ],
});
global.apiGet = (path) => Promise.resolve(
  String(path || '') === '/api/jobs/job-selected'
    ? {
        ok: true,
        job: {
          job_id: 'job-selected',
          origin_backend_mode: 'file_emergency',
          origin_authoritative_backend: 'files',
          origin_backend_session_id: 'session-1',
          origin_recovery: {
            recovery_action: 'fallback_export',
            fallback_export_source: 'legacy-tree',
          },
        },
      }
    : { ok: true, job: null }
);
selectedJobId = 'job-selected';
appPartJobs.refreshJobs({ mode: 'user' });
flush().then(() => flush()).then(() => {
  console.log(JSON.stringify({ html: document.getElementById('jobsList').innerHTML }));
});
"""
    )
    result = _run_node(script)
    assert "origin file_emergency/files" in result["html"]
    assert "session=session-1" in result["html"]
    assert "action=fallback_export" in result["html"]
    assert "detail=legacy-tree" in result["html"]


def test_jobs_list_selected_item_renders_legacy_origin_fallback() -> None:
    script = (
        _prelude()
        + """
global.apiGetETag = () => Promise.resolve({
  ok: true,
  jobs: [
    {
      job_id: 'job-selected',
      status: 'success',
      created_utc: '2026-03-25T09:15:00Z',
      issue_id: '382',
      commit_summary: 'Legacy',
      patch_basename: 'issue_382_v1.zip',
      mode: 'patch',
    },
  ],
});
global.apiGet = (path) => Promise.resolve(
  String(path || '') === '/api/jobs/job-selected'
    ? { ok: true, job: { job_id: 'job-selected' } }
    : { ok: true, job: null }
);
selectedJobId = 'job-selected';
appPartJobs.refreshJobs({ mode: 'user' });
flush().then(() => flush()).then(() => {
  console.log(JSON.stringify({ html: document.getElementById('jobsList').innerHTML }));
});
"""
    )
    result = _run_node(script)
    assert "origin legacy/no-origin-evidence" in result["html"]


def test_operator_info_bridge_assigns_window_hooks_and_renders_backend_status() -> None:
    script = (
        _info_pool_prelude()
        + """
degradedNotes = ["runtime dispatcher unavailable"];
window.PH_SET_OPERATOR_INFO_SNAPSHOT({
  cleanup_recent_status: [],
  backend_mode_status: {
    mode: "file_emergency",
    authoritative_backend: "files",
    backend_session_id: "session-450",
    recovery_status: "fallback",
    recovery_action: "fallback_export",
    recovery_detail: "legacy-tree",
    degraded: true,
  },
});
const infoPool = registry.get("app_part_info_pool");
infoPool.renderInfoPoolUi();
console.log(JSON.stringify({
  hasGet: typeof window.PH_GET_OPERATOR_INFO_SNAPSHOT,
  hasSet: typeof window.PH_SET_OPERATOR_INFO_SNAPSHOT,
  hasSync: typeof window.PH_INFO_POOL_SYNC_LEGACY_DEGRADED_BANNER,
  operatorMode: String(
    window.PH_GET_OPERATOR_INFO_SNAPSHOT().backend_mode_status.mode || ""
  ),
  strip: document.getElementById("uiStatusBar").textContent,
  banner: document.getElementById("uiDegradedBanner").textContent,
}));
"""
    )
    result = _run_node(script)
    assert result["hasGet"] == "function"
    assert result["hasSet"] == "function"
    assert result["hasSync"] == "function"
    assert result["operatorMode"] == "file_emergency"
    assert result["strip"] == "DEGRADED MODE: Backend file_emergency: fallback_export; legacy-tree"
    assert result["banner"] == "Backend file_emergency: fallback_export; legacy-tree"


def test_header_diagnostics_do_not_decide_backend_degraded_note() -> None:
    script = (
        _info_pool_prelude()
        + """
renderHeaderFromDiagnostics({
  ok: true,
  queue: {},
  lock: {},
  runs: {},
  stats: {},
  backend: {
    mode: "file_emergency",
    last_recovery: {
      recovery_action: "fallback_export",
      fallback_export_errors: ["legacy-tree"],
    },
  },
}, "server: 127.0.0.1:8080");
registry.get("app_part_info_pool").renderInfoPoolUi();
console.log(JSON.stringify({
  backendDegradedNote,
  strip: document.getElementById("uiStatusBar").textContent,
}));
"""
    )
    result = _run_node(script)
    assert result["backendDegradedNote"] == ""
    assert result["strip"] == "(idle)"
