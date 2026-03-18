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
    live_path = repo_root / "scripts" / "patchhub" / "static" / "patchhub_live_ui.js"
    script = f"""
const fs = require("fs");
const vm = require("vm");
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
global.fetch = () => Promise.reject(new Error("unused"));
global.EventSource = function() {{
  this.addEventListener = () => {{}};
  this.close = () => {{}};
}};
vm.runInThisContext(liveSrc, {{ filename: {json.dumps(str(live_path))} }});
const ui = global.window.AMP_PATCHHUB_UI;
const events = ui.liveEvents;
function capture(level) {{
  ui.setLiveLevel(level);
  ui.renderLiveLog();
  return document.getElementById("liveLog").textContent;
}}
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


def test_live_levels_follow_inheritance_and_debug_split() -> None:
    result = _run_node_scenario(
        """
events.push(
  { type: "hello", protocol: 1, runner_mode: "finalize_live", issue_id: "531" },
  {
    type: "log",
    ch: "CORE",
    sev: "INFO",
    kind: "TEXT",
    summary: true,
    msg: "START",
  },
  {
    type: "log",
    ch: "CORE",
    sev: "INFO",
    kind: "DO",
    stage: "PATCH_APPLY",
    summary: false,
    msg: "DO: PATCH_APPLY",
  },
  {
    type: "log",
    ch: "DETAIL",
    sev: "WARNING",
    kind: "TEXT",
    summary: false,
    msg: "WARNING: check me",
  },
  {
    type: "log",
    ch: "DETAIL",
    sev: "INFO",
    kind: "TEXT",
    summary: false,
    msg: "INFO: detail",
  },
  {
    type: "log",
    ch: "DETAIL",
    sev: "DEBUG",
    kind: "SUBPROCESS_STDOUT",
    summary: false,
    msg: "stdout tail",
  },
  {
    type: "log",
    ch: "DETAIL",
    sev: "DEBUG",
    kind: "SUBPROCESS_STDERR",
    summary: false,
    msg: "stderr tail",
  },
  {
    type: "log",
    ch: "DETAIL",
    sev: "ERROR",
    kind: "TEXT",
    summary: false,
    msg: "FAILED STEP OUTPUT",
    stderr: "boom",
  },
  {
    type: "reply",
    cmd: "ready",
    cmd_id: "patchhub_ready",
    ok: true,
    data: { ready: true },
  },
  { type: "result", ok: false, return_code: 1 },
);
process.stdout.write(
  JSON.stringify({
    migratedLevel: ui.setLiveLevel("debug"),
    quiet: capture("quiet"),
    normal: capture("normal"),
    warning: capture("warning"),
    verbose: capture("verbose"),
    debugHuman: capture("debug_human"),
    debugRaw: capture("debug_raw"),
  }),
);
""",
    )
    assert result["migratedLevel"] == "debug_raw"
    assert "START" in result["quiet"]
    assert "FAILED STEP OUTPUT" in result["quiet"]
    assert "STDERR:\nboom" in result["quiet"]
    assert "DO: PATCH_APPLY" not in result["quiet"]
    assert "DO: PATCH_APPLY" in result["normal"]
    assert "WARNING: check me" not in result["normal"]
    assert "stdout tail" not in result["normal"]
    assert "WARNING: check me" in result["warning"]
    assert "INFO: detail" not in result["warning"]
    assert "INFO: detail" in result["verbose"]
    assert "[stdout] stdout tail" in result["verbose"]
    assert "[stderr] stderr tail" in result["verbose"]
    assert "RESULT: FAIL" in result["verbose"]
    assert "rc=1" not in result["verbose"]
    assert "REPLY cmd=ready" in result["debugHuman"]
    assert "DO: PATCH_APPLY" in result["debugHuman"]
    assert "PATCH_APPLY | DO | INFO | DO: PATCH_APPLY" not in result["debugHuman"]
    assert '"type":"reply"' in result["debugRaw"]
    assert '"kind":"SUBPROCESS_STDOUT"' in result["debugRaw"]


def test_live_levels_group_failure_detail_from_subprocess_events() -> None:
    result = _run_node_scenario(
        """
events.push(
  {
    type: "log",
    ch: "CORE",
    sev: "INFO",
    kind: "DO",
    stage: "GATE_RUFF",
    summary: false,
    msg: "DO: GATE_RUFF",
  },
  {
    type: "log",
    ch: "DETAIL",
    sev: "DEBUG",
    kind: "SUBPROCESS_STDOUT",
    stage: "GATE_RUFF",
    summary: false,
    msg: "lint line",
  },
  {
    type: "log",
    ch: "DETAIL",
    sev: "DEBUG",
    kind: "SUBPROCESS_STDERR",
    stage: "GATE_RUFF",
    summary: false,
    msg: "boom line",
  },
  {
    type: "log",
    ch: "DETAIL",
    sev: "ERROR",
    kind: "TEXT",
    stage: "GATE_RUFF",
    summary: false,
    msg: "FAILED STEP OUTPUT",
  },
  { type: "result", ok: false, return_code: 1 },
);
process.stdout.write(
  JSON.stringify({
    normal: capture("normal"),
    verbose: capture("verbose"),
  }),
);
""",
    )
    assert "FAILED STEP OUTPUT" in result["normal"]
    assert "[stdout] lint line" in result["normal"]
    assert "[stderr] boom line" in result["normal"]
    assert "FAILED STEP OUTPUT" not in result["verbose"]
    assert "[stdout] lint line" in result["verbose"]
    assert "[stderr] boom line" in result["verbose"]
