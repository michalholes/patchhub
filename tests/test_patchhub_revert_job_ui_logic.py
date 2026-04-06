from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JOBS_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
REVERT_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs_revert.js"
SHELL_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "patchhub_shell.js"
APP_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js"


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
    jobs_path = json.dumps(str(JOBS_PATH))
    revert_path = json.dumps(str(REVERT_PATH))
    return f"""
import fs from "fs";
import vm from "vm";
const jobsSrc = fs.readFileSync({jobs_path}, "utf8");
const revertSrc = fs.readFileSync({revert_path}, "utf8");
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
global.window = {{
  PH: runtime,
  AMP_PATCHHUB_UI: {{
    saveLiveJobId() {{}},
    updateProgressPanelFromEvents() {{}},
  }},
  __ph_last_enqueued_job_id: "",
  __ph_last_enqueued_mode: "",
}};
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
global.Event = class Event {{ constructor(type) {{ this.type = type; }} }};
global.cfg = {{
  runner: {{ command: ["python3", "scripts/am_patch.py"] }},
  ui: {{ idle_auto_select_last_job: false }},
  server: {{ host: "127.0.0.1", port: 8080 }},
}};
global.selectedJobId = "job-selected";
global.suppressIdleOutput = false;
global.autoRefreshTimer = null;
global.idleSigs = {{ jobs: "", runs: "", patches: "", workspaces: "", hdr: "", snapshot: "" }};
global.idleNextDueMs = 0;
global.idleBackoffIdx = 0;
global.IDLE_BACKOFF_MS = [1000, 2000];
global.dirty = {{ issueId: false, commitMsg: false, patchPath: false, targetRepo: false }};
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
global.apiPost = () => Promise.resolve({{ ok: true, job_id: "revert-job" }});
global.apiGet = () => Promise.resolve({{ ok: true, job: null }});
global.apiGetETag = () => Promise.resolve({{ ok: true, unchanged: true }});
runtime.register("stub", {{
  getTrackedActiveJobId() {{ return ""; }},
  getTrackedActiveJob() {{ return null; }},
  getVisibleDurationNowMs() {{ return 0; }},
  setVisibleDurationSurface() {{ return true; }},
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
vm.runInThisContext(jobsSrc, {{ filename: {jobs_path} }});
vm.runInThisContext(revertSrc, {{ filename: {revert_path} }});
const appPartJobs = registry.get("app_part_jobs");
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
"""


def test_shell_has_no_jobs_revert_wrapper() -> None:
    src = SHELL_PATH.read_text(encoding="utf-8")
    assert "patchJobsExports" not in src
    assert "syncJobs(" not in src
    assert "data-revert-jobid" not in src


def test_app_loads_jobs_revert_part_before_wire_init() -> None:
    src = APP_PATH.read_text(encoding="utf-8")
    jobs_idx = src.index("/static/app_part_jobs.js")
    revert_idx = src.index("/static/app_part_jobs_revert.js")
    wire_idx = src.index("/static/app_part_wire_init.js")
    assert jobs_idx < revert_idx < wire_idx


def test_refresh_jobs_shows_revert_for_non_selected_job_after_detail_resolution() -> None:
    script = (
        _prelude()
        + """
let listCalls = 0;
global.apiGetETag = () => {
  listCalls += 1;
  return Promise.resolve({
    ok: true,
    jobs: [
      { job_id: 'job-selected', status: 'success', issue_id: '380' },
      {
        job_id: 'job-eligible',
        status: 'success',
        ended_utc: '2026-03-25T09:15:00Z',
        issue_id: '381',
      },
    ],
  });
};
global.apiGet = (path) => Promise.resolve(
  String(path || '') === '/api/jobs/job-eligible'
    ? {
        ok: true,
        job: {
          job_id: 'job-eligible',
          effective_runner_target_repo: 'patchhub',
          run_start_sha: 'aaa111',
          run_end_sha: 'bbb222',
          rollback_available: true,
          rollback_authority_kind: 'github',
          rollback_authority_source_ref: 'issue:381',
        },
      }
    : { ok: true, job: { job_id: 'job-selected' } }
);
appPartJobs.refreshJobs({ mode: 'user' });
flush().then(() => flush()).then(() => {
  console.log(JSON.stringify({
    listCalls,
    html: document.getElementById('jobsList').innerHTML,
  }));
});
"""
    )
    result = _run_node(script)
    assert result["listCalls"] == 1
    html = str(result["html"])
    assert 'data-revert-jobid="job-eligible"' in html
    assert 'data-revert-jobid="job-selected"' not in html


def test_revalidates_when_summary_state_changes() -> None:
    script = (
        _prelude()
        + """
let fetchCount = 0;
global.apiGet = () => {
  fetchCount += 1;
  if (fetchCount === 1) {
    return Promise.resolve({ ok: true, job: { job_id: 'job-eligible' } });
  }
  return Promise.resolve({
    ok: true,
    job: {
      job_id: 'job-eligible',
      effective_runner_target_repo: 'patchhub',
      run_start_sha: 'aaa111',
      run_end_sha: 'bbb222',
      rollback_available: true,
      rollback_authority_kind: 'github',
      rollback_authority_source_ref: 'issue:383',
    },
  });
};
appPartJobs.renderJobsFromResponse({ jobs: [
  { job_id: 'job-eligible', status: 'running', issue_id: '383' },
] });
flush().then(() => flush()).then(() => {
  const firstHtml = document.getElementById('jobsList').innerHTML;
  appPartJobs.renderJobsFromResponse({ jobs: [
    {
      job_id: 'job-eligible',
      status: 'success',
      ended_utc: '2026-03-25T09:15:00Z',
      issue_id: '383',
    },
  ] });
  return flush().then(() => flush()).then(() => {
    console.log(JSON.stringify({
      fetchCount,
      firstHtml,
      secondHtml: document.getElementById('jobsList').innerHTML,
    }));
  });
});
"""
    )
    result = _run_node(script)
    assert result["fetchCount"] == 2
    assert 'data-revert-jobid="job-eligible"' not in str(result["firstHtml"])
    assert 'data-revert-jobid="job-eligible"' in str(result["secondHtml"])


def test_missing_required_fields_keeps_revert_hidden() -> None:
    script = (
        _prelude()
        + """
global.apiGet = () => Promise.resolve({
  ok: true,
  job: {
    job_id: 'job-no-revert',
    effective_runner_target_repo: 'patchhub',
    run_start_sha: 'aaa111',
  },
});
appPartJobs.renderJobsFromResponse({ jobs: [
  {
    job_id: 'job-no-revert',
    status: 'success',
    ended_utc: '2026-03-25T09:16:00Z',
    issue_id: '384',
  },
] });
flush().then(() => flush()).then(() => {
  console.log(JSON.stringify({ html: document.getElementById('jobsList').innerHTML }));
});
"""
    )
    result = _run_node(script)
    assert 'data-revert-jobid="job-no-revert"' not in str(result["html"])
