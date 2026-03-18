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
global.window = {{
  AMP_PATCHHUB_UI: {{}},
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
    has(name) {{
      for (const exports of registry.values()) {{
        if (exports && typeof exports[name] === "function") return true;
      }}
      return false;
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
  getElementById(id) {{
    if (!elements.has(String(id))) elements.set(String(id), makeNode(String(id)));
    return elements.get(String(id));
  }},
}};
global.fetch = (url) => Promise.resolve({{
  status: 200,
  text: () =>
    Promise.resolve(
      JSON.stringify({{
        ok: true,
        job: {{
          job_id: "job-old",
          status: "success",
          applied_files: ["old.txt"],
        }},
      }}),
    ),
}});
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
    proc = subprocess.run(
        [node, "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def test_new_tracked_job_replaces_retained_terminal_state() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-old");
ui.openLiveStream("job-old");
__lastEventSource.listeners.end({
  data: JSON.stringify({ status: "success", reason: "job_completed" }),
});
await flush(80);
window.__ph_last_enqueued_job_id = "job-new";
window.__ph_last_enqueued_mode = "finalize_live (-f)";
ui.saveLiveJobId("job-new");
ui.openLiveStream("job-new");
await flush(80);
const tracked = window.PH.call("getTrackedActiveJob", [
  { job_id: "job-old", status: "success", mode: "patch" },
]);
process.stdout.write(
  JSON.stringify({
    trackedJobId: tracked ? tracked.job_id : "",
    trackedStatus: tracked ? tracked.status : "",
    activeHtml: document.getElementById("activeJob").innerHTML,
    summaryText: document.getElementById("progressSummary").textContent,
    appliedHidden: document.getElementById("progressApplied").classList.contains(
      "hidden",
    ),
  }),
);
"""
    )
    assert result["trackedJobId"] == "job-new"
    assert result["trackedStatus"] == "queued"
    assert "job-new" in result["activeHtml"]
    assert "queued" in result["activeHtml"]
    assert result["summaryText"] == "STATUS: QUEUED"
    assert result["appliedHidden"] is True


def test_live_ui_keeps_20000_most_recent_events() -> None:
    result = _run_node_scenario(
        """
ui.saveLiveJobId("job-retain");
ui.openLiveStream("job-retain");
for (let idx = 0; idx < 20005; idx += 1) {
  __lastEventSource.onmessage({
    data: JSON.stringify({ type: "log", msg: String(idx) }),
  });
}
await flush(80);
process.stdout.write(
  JSON.stringify({
    length: window.AMP_PATCHHUB_UI.liveEvents.length,
    first: window.AMP_PATCHHUB_UI.liveEvents[0].msg,
    last: window.AMP_PATCHHUB_UI.liveEvents[window.AMP_PATCHHUB_UI.liveEvents.length - 1].msg,
  }),
);
"""
    )
    assert result == {"length": 20000, "first": "5", "last": "20004"}
