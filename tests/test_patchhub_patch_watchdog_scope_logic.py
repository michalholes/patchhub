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


def _node_script(body: str) -> str:
    watchdog_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_patch_watchdog.js"
    return (
        """
import fs from "fs";
import vm from "vm";
const registry = new Map();
const nodes = {
  patchPath: { value: "", disabled: false },
  issueId: { value: "123", disabled: false },
  commitMsg: { value: "msg", disabled: false },
  targetRepo: { value: "patchhub", disabled: false },
};
const statCalls = [];
const validateCalls = [];
const pending = [];
global.__protected = false;
global.window = {
  PH: {
    register(name, exports) { registry.set(String(name), exports || {}); },
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
global.cfg = { paths: { patches_root: "patches", upload_dir: "patches/incoming" } };
global.document = {
  getElementById(id) {
    return Object.prototype.hasOwnProperty.call(nodes, id) ? nodes[id] : null;
  },
};
global.el = (id) => document.getElementById(id);
global.apiGet = (url) => {
  statCalls.push(String(url));
  return new Promise((resolve) => { pending.push(resolve); });
};
global.validateAndPreview = () => { validateCalls.push("validate"); };
window.PH.register("jobs_state", {
  isProtectedRerunLatestLifecycleActive() { return global.__protected; },
});
const src = fs.readFileSync("""
        + json.dumps(str(watchdog_path))
        + """, "utf8");
vm.runInThisContext(src, { filename: """
        + json.dumps(str(watchdog_path))
        + """ });
const flush = async () => {
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
};
"""
        + body
    )


def test_inventory_monitored_missing_path_clears_start_form() -> None:
    result = _run_node(
        _node_script(
            """
document.getElementById("patchPath").value = "patches/issue_376_v2.zip";
document.getElementById("issueId").value = "376";
document.getElementById("commitMsg").value = "keep";
window.PH.call("tickMissingPatchClear", { mode: "idle" });
pending[0]({ ok: true, exists: false });
await flush();
process.stdout.write(JSON.stringify({
  statCalls,
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  validateCalls: validateCalls.length,
}));
"""
        )
    )
    assert result["statCalls"] == ["/api/fs/stat?path=issue_376_v2.zip"]
    assert result["issueId"] == ""
    assert result["commitMsg"] == ""
    assert result["patchPath"] == ""
    assert result["validateCalls"] == 1


def test_inventory_monitored_missing_path_preserves_target_repo() -> None:
    result = _run_node(
        _node_script(
            """
document.getElementById("patchPath").value = "patches/issue_376_v2.zip";
document.getElementById("issueId").value = "376";
document.getElementById("commitMsg").value = "keep";
document.getElementById("targetRepo").value = "patchhub";
window.PH.call("tickMissingPatchClear", { mode: "idle" });
pending[0]({ ok: true, exists: false });
await flush();
process.stdout.write(JSON.stringify({
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  targetRepo: document.getElementById("targetRepo").value,
  validateCalls: validateCalls.length,
}));
"""
        )
    )
    assert result == {
        "issueId": "",
        "commitMsg": "",
        "patchPath": "",
        "targetRepo": "patchhub",
        "validateCalls": 1,
    }


def test_successful_and_unsuccessful_paths_skip_stat_and_preserve_form() -> None:
    result = _run_node(
        _node_script(
            """
document.getElementById("patchPath").value = "patches/successful/issue_376_v1.zip";
document.getElementById("issueId").value = "376";
document.getElementById("commitMsg").value = "ready";
window.PH.call("tickMissingPatchClear", { mode: "idle" });
document.getElementById("patchPath").value = "unsuccessful/issue_376_v1.zip";
window.PH.call("tickMissingPatchClear", { mode: "idle" });
await flush();
process.stdout.write(JSON.stringify({
  statCalls,
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  validateCalls: validateCalls.length,
}));
"""
        )
    )
    assert result["statCalls"] == []
    assert result["issueId"] == "376"
    assert result["commitMsg"] == "ready"
    assert result["patchPath"] == "unsuccessful/issue_376_v1.zip"
    assert result["validateCalls"] == 0


def test_archived_rerun_latest_path_stays_loaded_after_watchdog_tick() -> None:
    result = _run_node(
        _node_script(
            """
global.__protected = true;
document.getElementById("patchPath").value = "patches/issue_376_v2.zip";
document.getElementById("issueId").value = "376";
document.getElementById("commitMsg").value = "rerun latest";
document.getElementById("targetRepo").value = "patchhub";
window.PH.call("tickMissingPatchClear", { mode: "active" });
await flush();
process.stdout.write(JSON.stringify({
  statCalls,
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  targetRepo: document.getElementById("targetRepo").value,
  monitored: window.PH.call("isInventoryMonitoredPatchRel", "issue_376_v2.zip"),
}));
"""
        )
    )
    assert result == {
        "statCalls": [],
        "issueId": "376",
        "commitMsg": "rerun latest",
        "patchPath": "patches/issue_376_v2.zip",
        "targetRepo": "patchhub",
        "monitored": True,
    }


def test_stale_monitored_response_does_not_clear_archived_current_form() -> None:
    result = _run_node(
        _node_script(
            """
document.getElementById("patchPath").value = "patches/issue_1_v1.zip";
document.getElementById("issueId").value = "376";
document.getElementById("commitMsg").value = "keep";
document.getElementById("targetRepo").value = "patchhub";
window.PH.call("tickMissingPatchClear", { mode: "idle" });
global.__protected = true;
pending[0]({ ok: true, exists: false });
await flush();
process.stdout.write(JSON.stringify({
  statCalls,
  issueId: document.getElementById("issueId").value,
  commitMsg: document.getElementById("commitMsg").value,
  patchPath: document.getElementById("patchPath").value,
  targetRepo: document.getElementById("targetRepo").value,
  validateCalls: validateCalls.length,
}));
"""
        )
    )
    assert result == {
        "statCalls": ["/api/fs/stat?path=issue_1_v1.zip"],
        "issueId": "376",
        "commitMsg": "keep",
        "patchPath": "patches/issue_1_v1.zip",
        "targetRepo": "patchhub",
        "validateCalls": 0,
    }
