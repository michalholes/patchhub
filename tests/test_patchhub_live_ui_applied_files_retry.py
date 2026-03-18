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
    progress_path = repo_root / "scripts" / "patchhub" / "static" / "patchhub_progress_ui.js"
    live_path = repo_root / "scripts" / "patchhub" / "static" / "patchhub_live_ui.js"
    script = f"""
const fs = require("fs");
const vm = require("vm");
const progressSrc = fs.readFileSync({json.dumps(str(progress_path))}, "utf8");
const liveSrc = fs.readFileSync({json.dumps(str(live_path))}, "utf8");
const elements = new Map();
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
const fetchUrls = [];
const detailReplies = [
  {{
    ok: true,
    job: {{
      job_id: "job-512",
      status: "success",
      applied_files: [],
    }},
  }},
  {{
    ok: true,
    job: {{
      job_id: "job-512",
      status: "success",
      applied_files: ["scripts/patchhub/static/patchhub_live_ui.js"],
    }},
  }},
];
global.window = {{
  AMP_PATCHHUB_UI: {{}},
  PH: {{ register() {{}}, call() {{ return null; }} }},
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
  getElementById(id) {{
    if (!elements.has(String(id))) elements.set(String(id), makeNode(String(id)));
    return elements.get(String(id));
  }},
}};
global.fetch = (url) => {{
  fetchUrls.push(String(url));
  const payload = detailReplies.length ? detailReplies.shift() : detailReplies[0];
  return Promise.resolve({{
    status: 200,
    text: () => Promise.resolve(JSON.stringify(payload)),
  }});
}};
global.EventSource = function(url) {{
  this.url = url;
  this.listeners = {{}};
  this.addEventListener = (name, cb) => {{
    this.listeners[name] = cb;
  }};
  this.close = () => {{
    this.closed = true;
  }};
  global.__lastEventSource = this;
}};
vm.runInThisContext(progressSrc, {{ filename: {json.dumps(str(progress_path))} }});
vm.runInThisContext(liveSrc, {{ filename: {json.dumps(str(live_path))} }});
const ui = global.window.AMP_PATCHHUB_UI;
const flush = async (ms = 0) => {{
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, ms));
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


def test_end_event_forces_second_applied_files_fetch() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-512");
ui.openLiveStream("job-512");
__lastEventSource.onmessage({
  data: JSON.stringify({ type: "result", ok: true, return_code: 0 }),
});
await flush(80);
const beforeEndHtml = document.getElementById("progressApplied").innerHTML;
__lastEventSource.listeners.end({
  data: JSON.stringify({ status: "success", reason: "job_completed" }),
});
await flush(0);
const afterEndHtml = document.getElementById("progressApplied").innerHTML;
process.stdout.write(
  JSON.stringify({
    fetchCount: fetchUrls.length,
    firstUrl: fetchUrls[0] || "",
    beforeEndHtml,
    afterEndHtml,
    liveStatus: document.getElementById("liveStreamStatus").textContent,
  }),
);
"""
    )
    assert result["fetchCount"] == 2
    assert result["firstUrl"].endswith("/api/jobs/job-512")
    assert "Applied files unavailable" in result["beforeEndHtml"]
    assert "Applied files (1)" in result["afterEndHtml"]
    assert "patchhub_live_ui.js" in result["afterEndHtml"]
    assert result["liveStatus"] == "ended (success) [job_completed]"


def test_end_event_replaces_stale_running_summary() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-720");
ui.setLiveLevel("debug_human");
ui.openLiveStream("job-720");
__lastEventSource.onmessage({
  data: JSON.stringify({
    type: "log",
    kind: "DO",
    stage: "GATE_PYTEST",
    msg: "DO: GATE_PYTEST",
  }),
});
await flush(80);
const beforeEndSummary = document.getElementById("progressSummary").textContent;
__lastEventSource.listeners.end({
  data: JSON.stringify({ status: "success", reason: "job_completed" }),
});
await flush(80);
process.stdout.write(
  JSON.stringify({
    beforeEndSummary,
    afterEndSummary: document.getElementById("progressSummary").textContent,
    liveLog: document.getElementById("liveLog").textContent,
  }),
);
"""
    )
    assert result["beforeEndSummary"] == "DO: GATE_PYTEST"
    assert result["afterEndSummary"] == "RESULT: SUCCESS"
    assert "DO: GATE_PYTEST" in result["liveLog"]
