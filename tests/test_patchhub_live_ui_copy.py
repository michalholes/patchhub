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
    contains: (name) => items.has(String(name)),
  }};
}}
function makeNode(id) {{
  return {{
    id,
    nodeType: 1,
    innerHTML: "",
    textContent: "",
    value: "",
    parentElement: null,
    parentNode: null,
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
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}} }},
  getSelection() {{ return global.__selection; }},
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
const liveLog = document.getElementById("liveLog");
liveLog.textContent = "line1\\nline2";
const child = {{ nodeType: 3, parentNode: liveLog }};
global.__selection = {{
  rangeCount: 1,
  toString() {{ return "line2"; }},
  getRangeAt() {{ return {{ commonAncestorContainer: child }}; }},
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


def test_live_copy_helpers_use_rendered_text_and_selection() -> None:
    result = _run_node_scenario(
        """
process.stdout.write(JSON.stringify({
  selectedHelper: ui.getLiveLogSelectedText(),
  renderedHelper: ui.getLiveLogRenderedText(),
}));
"""
    )
    assert result["selectedHelper"] == "line2"
    assert result["renderedHelper"] == "line1\nline2"
