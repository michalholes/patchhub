from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_jobs.js"


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
    return f"""
import fs from "fs";
import vm from "vm";
const src = fs.readFileSync({json.dumps(str(SCRIPT_PATH))}, "utf8");
const elements = new Map();
const registry = new Map();
function makeClassList() {{
  const items = new Set();
  return {{
    add: (...names) => names.forEach((name) => items.add(String(name))),
    remove: (...names) => names.forEach((name) => items.delete(String(name))),
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
    style: {{}},
    parentElement: {{ classList: makeClassList() }},
    classList: makeClassList(),
    _listeners: {{}},
    addEventListener(name, cb) {{
      if (!this._listeners[name]) this._listeners[name] = [];
      this._listeners[name].push(cb);
    }},
    getAttribute(name) {{ return this[name] || null; }},
    setAttribute(name, value) {{ this[name] = String(value); }},
    dispatch(name, payload) {{
      const event = payload || {{ target: this }};
      (this._listeners[name] || []).forEach((cb) => cb(event));
    }},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
  }};
}}
global.window = {{
  AMP_PATCHHUB_UI: {{
    saveLiveJobId() {{}},
    updateProgressPanelFromEvents() {{}},
  }},
  PH: {{
    register(name, exports) {{ registry.set(String(name), exports || {{}}); }},
    call(name, ...args) {{
      for (const exports of registry.values()) {{
        if (exports && typeof exports[name] === "function") return exports[name](...args);
      }}
      return null;
    }},
    has(name) {{
      for (const exports of registry.values()) {{
        if (exports && typeof exports[name] === "function") return true;
      }}
      return false;
    }},
  }},
  __uiStatus: [],
  __uiErrors: [],
}};
global.document = {{
  hidden: false,
  getElementById(id) {{
    const key = String(id);
    if (!elements.has(key)) elements.set(key, makeNode(key));
    return elements.get(key);
  }},
}};
global.cfg = {{
  runner: {{ command: ["python3", "scripts/am_patch.py"] }},
  ui: {{ idle_auto_select_last_job: false }},
  server: {{ host: "127.0.0.1", port: 8080 }},
}};
global.localStorage = {{ getItem() {{ return null; }}, setItem() {{}} }};
global.AMP_UI = window.AMP_PATCHHUB_UI;
global.selectedJobId = "";
global.suppressIdleOutput = false;
global.autoRefreshTimer = null;
global.idleSigs = {{ jobs: "", runs: "", workspaces: "", hdr: "", snapshot: "" }};
global.idleNextDueMs = 0;
global.idleBackoffIdx = 0;
global.IDLE_BACKOFF_MS = [1000, 2000];
global.workspacesCache = [];
global.dirty = {{ issueId: false, commitMsg: false, patchPath: false, targetRepo: false }};
global.clearParsedState = () => {{}};
global.setParseHint = () => {{}};
global.setUiStatus = (msg) => window.__uiStatus.push(String(msg || ""));
global.setUiError = (msg) => window.__uiErrors.push(String(msg || ""));
global.setPre = () => {{}};
global.normalizePatchPath = (value) => String(value || "").trim();
global.escapeHtml = (s) => String(s || "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/\"/g, "&quot;")
  .replace(/'/g, "&#39;");
global.el = (id) => document.getElementById(id);
global.apiGetETag = () => Promise.resolve({{ ok: true, unchanged: true }});
global.apiGet = (path) => Promise.resolve({{ ok: true, job: null, path }});
global.apiPost = (path, body) => Promise.resolve({{ ok: true, path, body }});
window.PH.register("stub", {{
  validateAndPreview() {{ return true; }},
  renderActiveJob() {{}},
  getLiveJobId() {{ return ""; }},
  hasTrackedActiveJob() {{ return false; }},
  openLiveStream(jobId) {{ global.__openedLiveJobId = String(jobId || ""); }},
  closeLiveStream() {{}},
  loadLiveJobId() {{ return null; }},
  jobSummaryDurationSeconds() {{ return ""; }},
  renderRunsFromResponse() {{}},
  renderWorkspacesFromResponse() {{}},
  renderHeaderFromSummary() {{}},
  clearGateOverrides() {{}},
  refreshJobs() {{ global.__refreshJobsCalls = (global.__refreshJobsCalls || 0) + 1; }},
  getTrackedActiveJobId() {{ return ""; }},
  isNonTerminalJobStatus(status) {{
    return status === "queued" || status === "running";
  }},
}});
vm.runInThisContext(src, {{ filename: {json.dumps(str(SCRIPT_PATH))} }});
"""


def test_jobs_module_contains_revert_control_and_route() -> None:
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'data-revert-jobid="' in src
    assert '"/api/jobs/" + encodeURIComponent(sourceJobId) + "/revert"' in src
    assert "detailHasRevertFields" in src


def test_jobs_list_renders_revert_only_for_selected_job_with_required_fields() -> None:
    script = (
        _prelude()
        + """
selectedJobId = "job-eligible";
jobDetailCache["job-eligible"] = {
  job_id: "job-eligible",
  effective_runner_target_repo: "patchhub",
  run_start_sha: "aaa111",
  run_end_sha: "bbb222",
};
renderJobsFromResponse({ jobs: [
  {
    job_id: "job-eligible",
    status: "success",
    mode: "patch",
    issue_id: "380",
    commit_summary: "Eligible",
  },
  {
    job_id: "job-other",
    status: "success",
    mode: "patch",
    issue_id: "381",
    commit_summary: "Other",
  },
] });
console.log(JSON.stringify({ html: document.getElementById("jobsList").innerHTML }));
"""
    )
    result = _run_node(script)
    html = str(result["html"])
    assert 'data-revert-jobid="job-eligible"' in html
    assert 'data-revert-jobid="job-other"' not in html


def test_trigger_revert_job_posts_route_and_selects_new_live_job() -> None:
    script = (
        _prelude()
        + """
global.apiPost = (path, body) => Promise.resolve({
  ok: true,
  job_id: "job-revert-1",
  job: { job_id: "job-revert-1", mode: "revert_job" },
  path,
  body,
});
selectedJobId = "job-source";
triggerRevertJob("job-source").then((ok) => {
  console.log(JSON.stringify({
    ok,
    selectedJobId,
    openedLiveJobId: global.__openedLiveJobId || "",
    refreshJobsCalls: global.__refreshJobsCalls || 0,
    uiStatus: window.__uiStatus,
  }));
});
"""
    )
    result = _run_node(script)
    assert result["ok"] is True
    assert result["selectedJobId"] == "job-revert-1"
    assert result["openedLiveJobId"] == "job-revert-1"
    assert result["refreshJobsCalls"] == 1
    assert any(
        str(item).startswith("revert: ok job_id=job-revert-1") for item in result["uiStatus"]
    )
