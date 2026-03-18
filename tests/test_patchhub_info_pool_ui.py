from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _node_prelude(*script_paths: Path) -> str:
    src_lines = []
    run_lines = []
    for idx, path in enumerate(script_paths):
        src_lines.append(f'const src{idx} = fs.readFileSync({json.dumps(str(path))}, "utf8");')
        run_lines.append(f"vm.runInThisContext(src{idx}, {{ filename: {json.dumps(str(path))} }});")
    return (
        """
import fs from "fs";
import vm from "vm";
const elements = new Map();
const registry = new Map();
function makeClassList() {
  const items = new Set();
  return {
    add: (...names) => names.forEach((name) => items.add(String(name))),
    remove: (...names) => names.forEach((name) => items.delete(String(name))),
    toggle: (name, force) => {
      const key = String(name);
      const enabled = force === undefined ? !items.has(key) : !!force;
      if (enabled) items.add(key);
      else items.delete(key);
      return enabled;
    },
    contains: (name) => items.has(String(name)),
  };
}
function makeNode(id) {
  return {
    id,
    innerHTML: "",
    textContent: "",
    value: "",
    disabled: false,
    classList: makeClassList(),
    _listeners: {},
    addEventListener(name, cb) {
      if (!this._listeners[name]) this._listeners[name] = [];
      this._listeners[name].push(cb);
    },
    removeEventListener() {},
    setAttribute(name, value) { this[name] = String(value); },
    getAttribute(name) { return this[name] || null; },
    dispatch(name, payload) {
      const event = payload || { target: this, key: "" };
      event.target = event.target || this;
      event.preventDefault = event.preventDefault || (() => {});
      (this._listeners[name] || []).forEach((cb) => cb(event));
    },
  };
}
global.window = {
  AMP_PATCHHUB_UI: {},
  PH: {
    register(name, exports) {
      registry.set(String(name), exports || {});
    },
    call(name, ...args) {
      for (const exports of registry.values()) {
        if (exports && typeof exports[name] === "function") {
          return exports[name](...args);
        }
      }
      return null;
    },
    has(name) {
      for (const exports of registry.values()) {
        if (exports && typeof exports[name] === "function") return true;
      }
      return false;
    },
  },
};
global.document = {
  addEventListener() {},
  getElementById(id) {
    const key = String(id);
    if (!elements.has(key)) elements.set(key, makeNode(key));
    return elements.get(key);
  },
};
global.localStorage = { getItem() { return null; }, setItem() {} };
global.el = (id) => document.getElementById(id);
"""
        + "\n".join(src_lines)
        + "\n"
        + "\n".join(run_lines)
    )


def test_info_pool_strip_prefers_degraded_then_latest_hint_then_status() -> None:
    app_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js"
    pool_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_info_pool.js"
    script = (
        _node_prelude(app_path, pool_path)
        + """
window.PH.call("initInfoPoolUi");
setInfoPoolHint("parse", "missing raw command");
window.PH.call("renderInfoPoolUi");
const strip = document.getElementById("uiStatusBar");
const hintSummary = strip.textContent;
setInfoPoolHint("parse", "");
pushUiStatusLine("upload: ok");
const statusSummary = strip.textContent;
rememberDegraded("capability missing: info pool");
const degradedSummary = strip.textContent;
process.stdout.write(JSON.stringify({
  hintSummary,
  statusSummary,
  degradedSummary,
}));
"""
    )
    result = _run_node(script)
    assert result["hintSummary"] == "missing raw command"
    assert result["statusSummary"] == "upload: ok"
    assert result["degradedSummary"] == "DEGRADED MODE: capability missing: info pool"


def test_info_pool_strip_opens_modal_on_click() -> None:
    app_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js"
    pool_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_info_pool.js"
    script = (
        _node_prelude(app_path, pool_path)
        + """
window.PH.call("initInfoPoolUi");
setInfoPoolHint("upload", "Uploaded: patches/incoming/issue_320.zip");
window.PH.call("renderInfoPoolUi");
document.getElementById("uiStatusBar").dispatch("click");
const modal = document.getElementById("uiStatusModal");
process.stdout.write(JSON.stringify({
  open: !modal.classList.contains("hidden"),
  body: document.getElementById("uiStatusModalBody").innerHTML,
}));
"""
    )
    result = _run_node(script)
    assert result["open"] is True
    assert "Uploaded: patches/incoming/issue_320.zip" in result["body"]


def test_info_pool_strip_sets_pm_validation_state_classes_only_when_visible() -> None:
    app_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js"
    pm_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_pm_validation.js"
    pool_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_info_pool.js"
    script = (
        _node_prelude(app_path, pm_path, pool_path)
        + """
window.PH.call("initInfoPoolUi");
window.PH.call("setPmValidationPayload", { status: "pass" });
window.PH.call("renderInfoPoolUi");
const strip = document.getElementById("uiStatusBar");
const passState = {
  summary: strip.textContent,
  pass: strip.classList.contains("statusbar-pm-pass"),
  fail: strip.classList.contains("statusbar-pm-fail"),
};
window.PH.call("setPmValidationPayload", { status: "fail" });
window.PH.call("renderInfoPoolUi");
const failState = {
  summary: strip.textContent,
  pass: strip.classList.contains("statusbar-pm-pass"),
  fail: strip.classList.contains("statusbar-pm-fail"),
};
rememberDegraded("bootstrap fault");
const degradedState = {
  summary: strip.textContent,
  pass: strip.classList.contains("statusbar-pm-pass"),
  fail: strip.classList.contains("statusbar-pm-fail"),
};
process.stdout.write(JSON.stringify({ passState, failState, degradedState }));
"""
    )
    result = _run_node(script)
    assert result["passState"] == {
        "summary": "PM validation: PASS",
        "pass": True,
        "fail": False,
    }
    assert result["failState"] == {
        "summary": "PM validation: FAIL",
        "pass": False,
        "fail": True,
    }
    assert result["degradedState"] == {
        "summary": "DEGRADED MODE: bootstrap fault",
        "pass": False,
        "fail": False,
    }


def test_info_pool_strip_prefers_pm_validation_summary_over_hints() -> None:
    app_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js"
    pm_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_pm_validation.js"
    pool_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_info_pool.js"
    raw_output = json.dumps("RESULT: FAIL\nRULE PATCH_BASENAME: FAIL - issue_mismatch")
    script = (
        _node_prelude(app_path, pm_path, pool_path)
        + f"""
window.PH.call("initInfoPoolUi");
setInfoPoolHint("enqueue", "missing commit message or patch path");
window.PH.call("setPmValidationPayload", {{
  status: "fail",
  effective_mode: "initial",
  issue_id: "330",
  commit_message: "Use PM validator at zip load",
  patch_path: "issue_330_v1.zip",
  authority_sources: ["audiomason2-main_20260315.zip"],
  supplemental_files: [],
  raw_output: {raw_output},
}});
window.PH.call("renderInfoPoolUi");
process.stdout.write(JSON.stringify({{
  summary: document.getElementById("uiStatusBar").textContent,
}}));
"""
    )
    result = _run_node(script)
    assert result["summary"] == "PM validation: FAIL"


def test_info_pool_modal_shows_pm_validation_section_and_raw_output() -> None:
    app_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js"
    pm_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_pm_validation.js"
    pool_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_info_pool.js"
    raw_output = json.dumps("RESULT: PASS\nRULE MONOLITH: PASS - gate_passed")
    script = (
        _node_prelude(app_path, pm_path, pool_path)
        + f"""
window.PH.call("initInfoPoolUi");
window.PH.call("setPmValidationPayload", {{
  status: "pass",
  effective_mode: "repair-supplemental",
  issue_id: "330",
  commit_message: "Use PM validator at zip load",
  patch_path: "issue_330_v1.zip",
  authority_sources: ["patched_issue330_v01.zip", "live_workspace_snapshot"],
  supplemental_files: ["tests/test_sample.txt"],
  raw_output: {raw_output},
}});
window.PH.call("renderInfoPoolUi");
document.getElementById("uiStatusBar").dispatch("click");
process.stdout.write(JSON.stringify({{
  body: document.getElementById("uiStatusModalBody").innerHTML,
}}));
"""
    )
    result = _run_node(script)
    assert "PM validation" in result["body"]
    assert "repair-supplemental" in result["body"]
    assert "RESULT: PASS" in result["body"]
    assert "tests/test_sample.txt" in result["body"]
