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
const eventSources = [];
const deltaUrls = [];
const refreshCalls = [];
const renderCalls = [];
let nextDelta = {{ ok: true, resync_needed: true, seq: 0 }};
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
global.apiGetETag = (_key, _url, _opts) => {{
  refreshCalls.push({{ mode: _opts && _opts.mode }});
  return Promise.resolve(nextSnapshot);
}};
global.setUiError = (err) => {{ throw err; }};
global.EventSource = function(url) {{
  this.url = url;
  this.listeners = {{}};
  this.addEventListener = (name, cb) => {{
    this.listeners[name] = cb;
  }};
  this.close = () => {{}};
  eventSources.push(this);
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


def test_event_seq_is_not_used_as_since_seq() -> None:
    result = _run_node_scenario(
        """
nextSnapshot = {
  ok: true,
  seq: 5,
  snapshot: { jobs: [], runs: [], workspaces: [], header: {} },
  sigs: { snapshot: "s5" },
};
await refreshOverviewSnapshot({ mode: "latest" });
ensureSnapshotEvents();
const es = eventSources[0];
nextDelta = {
  ok: true,
  seq: 6,
  sigs: { snapshot: "s6" },
  jobs: { added: [], updated: [], removed: [] },
  runs: { added: [], updated: [], removed: [] },
  workspaces: { added: [], updated: [], removed: [] },
  header_changed: false,
};
es.listeners.snapshot_changed({
  data: JSON.stringify({ seq: 6, sigs: { snapshot: "s6" } }),
});
await flush();
process.stdout.write(JSON.stringify({ deltaUrl: deltaUrls[0] || "" }));
"""
    )
    assert result["deltaUrl"].endswith("since_seq=5")


def test_full_snapshot_fallback_stores_applied_seq_for_next_delta() -> None:
    result = _run_node_scenario(
        """
ensureSnapshotEvents();
const es = eventSources[0];
nextSnapshot = {
  ok: true,
  seq: 9,
  snapshot: { jobs: [], runs: [], workspaces: [], header: {} },
  sigs: { snapshot: "s9" },
};
es.listeners.snapshot_changed({
  data: JSON.stringify({ seq: 9, sigs: { snapshot: "s9" } }),
});
await flush();
nextDelta = {
  ok: true,
  seq: 10,
  sigs: { snapshot: "s10" },
  jobs: { added: [], updated: [], removed: [] },
  runs: { added: [], updated: [], removed: [] },
  workspaces: { added: [], updated: [], removed: [] },
  header_changed: false,
};
es.listeners.snapshot_changed({
  data: JSON.stringify({ seq: 10, sigs: { snapshot: "s10" } }),
});
await flush();
process.stdout.write(
  JSON.stringify({
    refreshCalls: refreshCalls.length,
    deltaUrl: deltaUrls[0] || "",
  }),
);
"""
    )
    assert result["refreshCalls"] >= 1
    assert result["deltaUrl"].endswith("since_seq=9")


def test_stale_event_is_ignored() -> None:
    result = _run_node_scenario(
        """
nextSnapshot = {
  ok: true,
  seq: 10,
  snapshot: { jobs: [], runs: [], workspaces: [], header: {} },
  sigs: { snapshot: "s10" },
};
await refreshOverviewSnapshot({ mode: "latest" });
ensureSnapshotEvents();
const es = eventSources[0];
es.listeners.snapshot_changed({
  data: JSON.stringify({ seq: 9, sigs: { snapshot: "s9" } }),
});
await flush();
process.stdout.write(
  JSON.stringify({
    deltaCalls: deltaUrls.length,
    refreshCalls: refreshCalls.length,
  }),
);
"""
    )
    assert result["deltaCalls"] == 0
    assert result["refreshCalls"] == 1
