from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _run_node_scenario(body: str) -> dict[str, object]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    repo_root = Path(__file__).resolve().parents[1]
    duration_path = repo_root / "scripts" / "patchhub" / "static" / "patchhub_visible_duration.js"
    progress_path = repo_root / "scripts" / "patchhub" / "static" / "patchhub_progress_ui.js"
    live_path = repo_root / "scripts" / "patchhub" / "static" / "patchhub_live_ui.js"
    jobs_path = repo_root / "scripts" / "patchhub" / "static" / "app_part_jobs.js"
    script = f"""
const fs = require("fs");
const vm = require("vm");
const durationSrc = fs.readFileSync({json.dumps(str(duration_path))}, "utf8");
const progressSrc = fs.readFileSync({json.dumps(str(progress_path))}, "utf8");
const liveSrc = fs.readFileSync({json.dumps(str(live_path))}, "utf8");
const jobsSrc = fs.readFileSync({json.dumps(str(jobs_path))}, "utf8");
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
      if (enabled) items.add(key);
      else items.delete(key);
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
    parentElement: {{ classList: makeClassList() }},
    classList: makeClassList(),
    addEventListener() {{}},
    removeEventListener() {{}},
    appendChild() {{}},
    focus() {{}},
  }};
}}
let nowMs = new Date("2026-03-14T08:00:05Z").getTime();
let perfNowMs = 5000;
Date.now = () => nowMs;
global.performance = {{ now: () => perfNowMs }};
global.window = {{
  AMP_PATCHHUB_UI: {{}},
  __ph_last_enqueued_mode: "",
  __ph_last_enqueued_job_id: "",
  PH: {{
    register(name, exports) {{
      registry.set(String(name), exports || {{}});
    }},
    call(name, ...args) {{
      for (const exports of registry.values()) {{
        if (exports && typeof exports[name] === "function") {{
          return exports[name](...args);
        }}
      }}
      return null;
    }},
  }},
  localStorage: {{
    _store: new Map(),
    getItem(key) {{
      return this._store.has(String(key)) ? this._store.get(String(key)) : null;
    }},
    setItem(key, value) {{
      this._store.set(String(key), String(value));
    }},
  }},
}};
global.localStorage = global.window.localStorage;
global.document = {{
  hidden: false,
  getElementById(id) {{
    if (!elements.has(String(id))) elements.set(String(id), makeNode(String(id)));
    return elements.get(String(id));
  }},
}};
global.el = (id) => global.document.getElementById(id);
global.escapeHtml = (value) => String(value)
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/\"/g, "&quot;");
global.cfg = {{ ui: {{ idle_auto_select_last_job: false }} }};
global.selectedJobId = "";
global.suppressIdleOutput = false;
global.idleSigs = {{ jobs: "", runs: "", workspaces: "", hdr: "", snapshot: "" }};
global.autoRefreshTimer = null;
global.idleNextDueMs = 0;
global.IDLE_BACKOFF_MS = [1000];
global.__intervals = new Map();
global.__nextIntervalId = 1;
global.setInterval = (fn) => {{
  const id = global.__nextIntervalId++;
  global.__intervals.set(id, fn);
  return id;
}};
global.clearInterval = (id) => {{
  global.__intervals.delete(Number(id));
}};
global.dirty = {{ issueId: false, commitMsg: false, patchPath: false }};
global.normalizePatchPath = (value) => String(value || "");
global.apiGet = () => Promise.resolve({{ ok: true }});
global.apiGetETag = () => Promise.resolve({{ ok: true, unchanged: true }});
global.setUiStatus = () => {{}};
global.setUiError = () => {{}};
global.setParseHint = () => {{}};
global.clearParsedState = () => {{}};
global.setPre = (id, payload) => {{
  global.document.getElementById(id).textContent = JSON.stringify(payload);
}};
global.fetch = (url) => Promise.resolve({{
  status: 200,
  text: () =>
    Promise.resolve(
      JSON.stringify({{
        ok: true,
        job: {{
          job_id: "job-42",
          status: "running",
          applied_files: [],
        }},
      }}),
    ),
}});
global.EventSource = function() {{
  this.addEventListener = () => {{}};
  this.close = () => {{}};
}};
vm.runInThisContext(durationSrc, {{ filename: {json.dumps(str(duration_path))} }});
vm.runInThisContext(progressSrc, {{ filename: {json.dumps(str(progress_path))} }});
vm.runInThisContext(liveSrc, {{ filename: {json.dumps(str(live_path))} }});
vm.runInThisContext(jobsSrc, {{ filename: {json.dumps(str(jobs_path))} }});
const ui = global.window.AMP_PATCHHUB_UI;
(async () => {{
{body}
}})().catch((err) => {{
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}});
"""
    proc = subprocess.run([node, "-e", script], cwd=repo_root, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def test_progress_skip_surface_and_active_elapsed_timer() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-42");
ui.liveEvents.push(
  {
    type: "log",
    kind: "DO",
    stage: "GATE_JS",
    msg: "DO: GATE_JS",
  },
  {
    type: "log",
    ch: "CORE",
    sev: "WARNING",
    kind: "TEXT",
    msg: "gate_js=SKIP (no_js_touched)",
  },
  {
    type: "log",
    kind: "OK",
    stage: "GATE_JS",
    msg: "OK: GATE_JS",
  },
);
const jobs = [
  {
    job_id: "job-42",
    status: "running",
    mode: "patch",
    issue_id: "322",
    started_utc: "2026-03-14T08:00:00Z",
  },
];
await ui.updateProgressPanelFromEvents({ jobs });
process.stdout.write(
  JSON.stringify({
    progressHtml: document.getElementById("progressSteps").innerHTML,
    progressElapsed: document.getElementById("progressElapsed").textContent,
    summaryText: document.getElementById("progressSummary").textContent,
    activeHtml: document.getElementById("activeJob").innerHTML,
    elapsed: ui.jobSummaryDurationSeconds("2026-03-14T08:00:00Z", ""),
  }),
);
""",
    )
    assert "GATE_JS" in result["progressHtml"]
    assert "SKIPPED (no_js_touched)" in result["progressHtml"]
    assert result["summaryText"] == "SKIP: GATE_JS (no_js_touched)"
    assert result["progressElapsed"] == "elapsed 5.0s"
    assert "elapsed=" not in result["activeHtml"]
    assert result["elapsed"] == "5.0"


def test_progress_non_skipped_gate_js_gets_duration_pill() -> None:
    result = _run_node_scenario(
        """
let nowMs = new Date("2026-03-14T08:00:05Z").getTime();
let perfNowMs = 0;
Date.now = () => nowMs;
performance.now = () => perfNowMs;
ui.saveLiveJobId("job-42b");
ui.liveEvents.push({
  type: "log",
  seq: 1,
  ts_mono_ms: 1000,
  kind: "DO",
  stage: "GATE_JS",
  msg: "DO: GATE_JS",
});
await ui.updateProgressPanelFromEvents({
  jobs: [
    {
      job_id: "job-42b",
      status: "running",
      mode: "patch",
      issue_id: "322",
      started_utc: "2026-03-14T08:00:00Z",
    },
  ],
});
const firstHtml = document.getElementById("progressSteps").innerHTML;
const timerIds = Array.from(global.__intervals.keys());
nowMs += 3000;
perfNowMs += 3000;
if (timerIds.length) {
  global.__intervals.get(timerIds[0])();
}
process.stdout.write(
  JSON.stringify({
    firstHtml,
    secondHtml: document.getElementById("progressSteps").innerHTML,
    tickerCount: window.PH.call("getVisibleDurationTickerCount"),
  }),
);
""",
    )
    assert "GATE_JS" in result["firstHtml"]
    assert "RUNNING (0.0s)" in result["firstHtml"]
    assert "RUNNING (3.0s)" in result["secondHtml"]
    assert result["tickerCount"] == 1


def test_jobs_list_elapsed_only_for_tracked_active_row() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-42");
window.PH.call("renderJobsFromResponse", {
  ok: true,
  jobs: [
    {
      job_id: "job-42",
      status: "running",
      mode: "patch",
      issue_id: "322",
      commit_summary: "tracked",
      started_utc: "2026-03-14T08:00:00Z",
    },
    {
      job_id: "job-77",
      status: "queued",
      mode: "patch",
      issue_id: "400",
      commit_summary: "other",
      started_utc: "2026-03-14T08:00:00Z",
    },
    {
      job_id: "job-88",
      status: "success",
      mode: "patch",
      issue_id: "500",
      commit_summary: "finished",
      started_utc: "2026-03-14T08:00:00Z",
      ended_utc: "2026-03-14T08:00:03Z",
    },
  ],
});
process.stdout.write(
  JSON.stringify({
    jobsHtml: document.getElementById("jobsList").innerHTML,
  }),
);
""",
    )
    assert "tracked" in result["jobsHtml"]
    assert "dur=5.0s" in result["jobsHtml"]
    assert "finished" in result["jobsHtml"]
    assert "dur=3.0s" in result["jobsHtml"]
    assert 'other</div><div class="job-meta">mode=patch</div>' in result["jobsHtml"]


def test_progress_elapsed_primes_from_jobs_response_and_survives_omitted_refresh() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-55");
window.PH.call("renderJobsFromResponse", {
  ok: true,
  jobs: [
    {
      job_id: "job-55",
      status: "running",
      mode: "patch",
      issue_id: "328",
      commit_summary: "tracked",
      started_utc: "2026-03-14T08:00:00Z",
    },
  ],
});
const before = document.getElementById("progressElapsed").textContent;
await ui.updateProgressPanelFromEvents();
process.stdout.write(
  JSON.stringify({
    before,
    after: document.getElementById("progressElapsed").textContent,
    hidden: document.getElementById("progressElapsed").classList.contains("hidden"),
  }),
);
""",
    )
    assert result["before"] == "elapsed 5.0s"
    assert result["after"] == "elapsed 5.0s"
    assert result["hidden"] is False


def test_progress_pytest_timer_advances_without_new_log_lines() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-55");
window.PH.call("renderJobsFromResponse", {
  ok: true,
  jobs: [
    {
      job_id: "job-55",
      status: "running",
      mode: "patch",
      issue_id: "328",
      commit_summary: "tracked",
      started_utc: "2026-03-14T08:00:00Z",
    },
  ],
});
ui.liveEvents.push({
  type: "log",
  seq: 1,
  ts_mono_ms: 1000,
  kind: "DO",
  stage: "GATE_PYTEST",
  msg: "DO: GATE_PYTEST",
});
const jobs = [
  {
    job_id: "job-55",
    status: "running",
    mode: "patch",
    issue_id: "328",
    started_utc: "2026-03-14T08:00:00Z",
  },
];
await ui.updateProgressPanelFromEvents({ jobs });
const firstHtml = document.getElementById("progressSteps").innerHTML;
const firstElapsed = document.getElementById("progressElapsed").textContent;
const timerIds = Array.from(global.__intervals.keys());
nowMs += 3000;
perfNowMs += 3000;
if (timerIds.length) {{
  global.__intervals.get(timerIds[0])();
}}
process.stdout.write(
  JSON.stringify({
    firstHtml,
    firstElapsed,
    secondHtml: document.getElementById("progressSteps").innerHTML,
    secondElapsed: document.getElementById("progressElapsed").textContent,
    jobsHtml: document.getElementById("jobsList").innerHTML,
    intervalCount: timerIds.length,
    tickerCount: window.PH.call("getVisibleDurationTickerCount"),
  }),
);
""",
    )
    assert result["intervalCount"] == 1
    assert result["tickerCount"] == 1
    assert result["firstElapsed"] == "elapsed 5.0s"
    assert "RUNNING (0.0s)" in result["firstHtml"]
    assert result["secondElapsed"] == "elapsed 8.0s"
    assert "dur=8.0s" in result["jobsHtml"]
    assert "RUNNING (3.0s)" in result["secondHtml"]


def test_progress_elapsed_clears_when_jobs_explicitly_empty() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-55");
window.PH.call("renderJobsFromResponse", {
  ok: true,
  jobs: [
    {
      job_id: "job-55",
      status: "running",
      mode: "patch",
      issue_id: "328",
      commit_summary: "tracked",
      started_utc: "2026-03-14T08:00:00Z",
    },
  ],
});
await ui.updateProgressPanelFromEvents({ jobs: [] });
process.stdout.write(
  JSON.stringify({
    elapsed: document.getElementById("progressElapsed").textContent,
    hidden: document.getElementById("progressElapsed").classList.contains("hidden"),
  }),
);
""",
    )
    assert result["elapsed"] == ""
    assert result["hidden"] is True


def test_progress_pytest_timer_cleans_up_after_finish() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-58");
const jobs = [
  {
    job_id: "job-58",
    status: "running",
    mode: "patch",
    issue_id: "329",
    started_utc: "2026-03-14T08:00:00Z",
  },
];
ui.liveEvents.push({
  type: "log",
  seq: 1,
  ts_mono_ms: 1000,
  kind: "DO",
  stage: "GATE_PYTEST",
  msg: "DO: GATE_PYTEST",
});
await ui.updateProgressPanelFromEvents({ jobs });
const runningIntervals = Array.from(global.__intervals.keys());
ui.liveEvents.push({
  type: "log",
  seq: 2,
  ts_mono_ms: 4500,
  kind: "OK",
  stage: "GATE_PYTEST",
  msg: "OK: GATE_PYTEST",
});
await ui.updateProgressPanelFromEvents({
  jobs: [
    {
      job_id: "job-58",
      status: "success",
      mode: "patch",
      issue_id: "329",
      started_utc: "2026-03-14T08:00:00Z",
      ended_utc: "2026-03-14T08:00:06Z",
    },
  ],
});
process.stdout.write(
  JSON.stringify({
    runningIntervalCount: runningIntervals.length,
    remainingIntervalCount: global.__intervals.size,
    progressHtml: document.getElementById("progressSteps").innerHTML,
    progressElapsed: document.getElementById("progressElapsed").textContent,
    tickerCount: window.PH.call("getVisibleDurationTickerCount"),
  }),
);
""",
    )
    assert result["runningIntervalCount"] == 1
    assert result["remainingIntervalCount"] == 0
    assert result["tickerCount"] == 0
    assert ">3.5s<" in result["progressHtml"]
    assert result["progressElapsed"] == "elapsed 6.0s"


def test_progress_pytest_duration_freezes_after_finish_and_terminal_end() -> None:
    result = _run_node_scenario(
        """
let nowMs = new Date("2026-03-14T08:00:10Z").getTime();
Date.now = () => nowMs;
ui.saveLiveJobId("job-56");
ui.liveEvents.push(
  {
    type: "log",
    seq: 1,
    ts_mono_ms: 1000,
    kind: "DO",
    stage: "GATE_PYTEST",
    msg: "DO: GATE_PYTEST",
  },
  {
    type: "log",
    seq: 2,
    ts_mono_ms: 4500,
    kind: "OK",
    stage: "GATE_PYTEST",
    msg: "OK: GATE_PYTEST",
  },
  {
    type: "control",
    event: "stream_end",
    status: "success",
    reason: "job_completed",
  },
);
const jobs = [
  {
    job_id: "job-56",
    status: "success",
    mode: "patch",
    issue_id: "328",
    started_utc: "2026-03-14T08:00:00Z",
    ended_utc: "2026-03-14T08:00:07Z",
  },
];
await ui.updateProgressPanelFromEvents({ jobs, forceAppliedFilesRetry: true });
const firstHtml = document.getElementById("progressSteps").innerHTML;
nowMs += 10000;
await ui.updateProgressPanelFromEvents({ jobs, forceAppliedFilesRetry: true });
process.stdout.write(
  JSON.stringify({
    firstHtml,
    secondHtml: document.getElementById("progressSteps").innerHTML,
    summaryText: document.getElementById("progressSummary").textContent,
  }),
);
""",
    )
    assert ">3.5s<" in result["firstHtml"]
    assert ">3.5s<" in result["secondHtml"]
    assert result["summaryText"] == "RESULT: SUCCESS"


def test_progress_mypy_skip_clears_duration_pill() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-57");
ui.liveEvents.push(
  {
    type: "log",
    seq: 1,
    ts_mono_ms: 1000,
    kind: "DO",
    stage: "GATE_MYPY",
    msg: "DO: GATE_MYPY",
  },
  {
    type: "log",
    seq: 2,
    ts_mono_ms: 1500,
    kind: "TEXT",
    ch: "CORE",
    sev: "WARNING",
    msg: "gate_mypy=SKIP (no_matching_files)",
  },
  {
    type: "log",
    seq: 3,
    ts_mono_ms: 2000,
    kind: "OK",
    stage: "GATE_MYPY",
    msg: "OK: GATE_MYPY",
  },
);
await ui.updateProgressPanelFromEvents({
  jobs: [
    {
      job_id: "job-57",
      status: "running",
      mode: "patch",
      issue_id: "328",
      started_utc: "2026-03-14T08:00:00Z",
    },
  ],
});
process.stdout.write(
  JSON.stringify({
    progressHtml: document.getElementById("progressSteps").innerHTML,
  }),
);
""",
    )
    assert "SKIPPED (no_matching_files)" in result["progressHtml"]
    assert "RUNNING (" not in result["progressHtml"]
    assert ">1.0s<" not in result["progressHtml"]
