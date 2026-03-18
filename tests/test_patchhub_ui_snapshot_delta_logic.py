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
    src_path = repo_root / "scripts" / "patchhub" / "static" / "app_part_snapshot_events.js"
    script = f"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync({json.dumps(str(src_path))}, "utf8");
const deltaUrls = [];
const renderCalls = [];
let nextDelta = {{
  ok: true,
  seq: 0,
  sigs: {{}},
  jobs: {{ added: [], updated: [], removed: [] }},
  runs: {{ added: [], updated: [], removed: [] }},
  workspaces: {{ added: [], updated: [], removed: [] }},
  header_changed: false,
}};
let nextSnapshot = {{
  ok: true,
  seq: 0,
  snapshot: {{ jobs: [], runs: [], workspaces: [], header: {{}} }},
  sigs: {{}},
}};
global.window = globalThis;
global.__ph_w = globalThis;
global.cfg = {{ server: {{ host: "127.0.0.1", port: 8099 }} }};
global.idleSigs = {{ snapshot: "", jobs: "", runs: "", workspaces: "", hdr: "" }};
global.document = {{ hidden: false }};
global.activeJobId = "";
global.renderJobsFromResponse = (payload) =>
  renderCalls.push({{ kind: "jobs", payload }});
global.renderHeaderFromSummary = (payload, base) =>
  renderCalls.push({{ kind: "header", payload, base }});
global.PH = {{
  register() {{}},
  call(name, ...args) {{
    const map = {{
      renderJobsFromResponse,
      renderHeaderFromSummary,
      renderRunsFromResponse: global.__ph_w.renderRunsFromResponse,
      renderWorkspacesFromResponse: global.__ph_w.renderWorkspacesFromResponse,
    }};
    const fn = map[name];
    return typeof fn === "function" ? fn(...args) : undefined;
  }},
}};
global.__ph_w.renderRunsFromResponse = (payload) =>
  renderCalls.push({{ kind: "runs", payload }});
global.__ph_w.renderWorkspacesFromResponse = (payload) =>
  renderCalls.push({{ kind: "workspaces", payload }});
global.apiGet = (url) => {{
  deltaUrls.push(String(url));
  return Promise.resolve(nextDelta);
}};
global.apiGetETag = () => Promise.resolve(nextSnapshot);
global.setUiError = (err) => {{ throw err; }};
global.EventSource = function() {{
  this.listeners = {{}};
  this.addEventListener = (name, cb) => {{
    this.listeners[name] = cb;
  }};
  this.close = () => {{}};
  global.__lastEventSource = this;
}};
vm.runInThisContext(src, {{ filename: {json.dumps(str(src_path))} }});
const flush = async () => {{
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}};
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


def test_delta_apply_updates_overview_cache_via_renderers() -> None:
    result = _run_node_scenario(
        """
nextSnapshot = {
  ok: true,
  seq: 5,
  snapshot: {
    jobs: [{ job_id: "job-1", status: "queued" }],
    runs: [],
    workspaces: [],
    header: { runs: { count: 1 } },
  },
  sigs: { snapshot: "s5" },
};
await refreshOverviewSnapshot({ mode: "latest" });
ensureSnapshotEvents();
nextDelta = {
  ok: true,
  seq: 6,
  sigs: { snapshot: "s6" },
  jobs: {
    added: [],
    updated: [{ job_id: "job-1", status: "running" }],
    removed: [],
  },
  runs: { added: [], updated: [], removed: [] },
  workspaces: { added: [], updated: [], removed: [] },
  header_changed: true,
  header: { runs: { count: 2 } },
};
__lastEventSource.listeners.snapshot_changed({
  data: JSON.stringify({ seq: 6, sigs: { snapshot: "s6" } }),
});
await flush();
const jobsCall = renderCalls.filter((item) => item.kind === "jobs").slice(-1)[0];
const headerCall = renderCalls.filter((item) => item.kind === "header").slice(-1)[0];
process.stdout.write(
  JSON.stringify({
    status: jobsCall.payload.jobs[0].status,
    headerCount: headerCall.payload.runs.count,
    deltaUrl: deltaUrls[0] || "",
  }),
);
"""
    )
    assert result["deltaUrl"].endswith("since_seq=5")
    assert result["status"] == "running"
    assert result["headerCount"] == 2
