from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_node_scenario(body: str) -> dict[str, object]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    live_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "patchhub_live_ui.js"
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
  const node = {{
    id,
    innerHTML: "",
    value: "",
    scrollTop: 0,
    scrollHeight: 0,
    parentElement: {{ classList: makeClassList() }},
    classList: makeClassList(),
    _listeners: {{}},
    setAttribute(name, value) {{ this[String(name)] = String(value); }},
    addEventListener(type, handler) {{ this._listeners[String(type)] = handler; }},
    removeEventListener() {{}},
    appendChild() {{}},
    focus() {{}},
    click() {{
      if (this._listeners.click) this._listeners.click({{ currentTarget: this }});
    }},
  }};
  Object.defineProperty(node, "textContent", {{
    get() {{
      return this._textContent || "";
    }},
    set(value) {{
      this._textContent = String(value || "");
      const lineCount = this._textContent ? this._textContent.split("\\n").length : 0;
      this.scrollHeight = lineCount * 20;
    }},
  }});
  node.textContent = "";
  return node;
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
const box = document.getElementById("liveLog");
document.getElementById("liveAutoscrollToggle");
(async () => {{
{body}
}})().catch((err) => {{
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}});
"""
    proc = subprocess.run([node, "-e", script], cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def test_live_autoscroll_load_restores_saved_state() -> None:
    result = _run_node_scenario(
        """
global.localStorage.setItem("amp.liveLogAutoscroll", "0");
ui.initLiveAutoscrollToggle();
ui.loadLiveAutoscroll();
const toggle = document.getElementById("liveAutoscrollToggle");
process.stdout.write(
  JSON.stringify({
    enabled: ui.getLiveAutoscrollEnabled(),
    ariaChecked: String(toggle["aria-checked"] || ""),
    isOn: toggle.classList.contains("is-on"),
  }),
);
""",
    )
    assert result["enabled"] is False
    assert result["ariaChecked"] == "false"
    assert result["isOn"] is False


def test_live_autoscroll_toggle_scrolls_only_when_enabled() -> None:
    result = _run_node_scenario(
        """
ui.initLiveAutoscrollToggle();
ui.loadLiveAutoscroll();
ui.liveEvents.push(
  { type: "log", sev: "INFO", summary: true, msg: "line1" },
  { type: "log", sev: "INFO", summary: true, msg: "line2" },
  { type: "log", sev: "INFO", summary: true, msg: "line3" },
);
box.scrollTop = 7;
ui.renderLiveLog();
const onScrollTop = box.scrollTop;
const toggle = document.getElementById("liveAutoscrollToggle");
toggle.click();
box.scrollTop = 11;
ui.liveEvents.push({ type: "log", sev: "INFO", summary: true, msg: "line4" });
ui.renderLiveLog();
process.stdout.write(
  JSON.stringify({
    onScrollTop,
    offScrollTop: box.scrollTop,
    stored: global.localStorage.getItem("amp.liveLogAutoscroll"),
    ariaChecked: String(toggle["aria-checked"] || ""),
    isOn: toggle.classList.contains("is-on"),
  }),
);
""",
    )
    assert result["onScrollTop"] == 60
    assert result["offScrollTop"] == 11
    assert result["stored"] == "0"
    assert result["ariaChecked"] == "false"
    assert result["isOn"] is False
