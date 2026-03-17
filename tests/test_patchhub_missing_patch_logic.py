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
    src_path = repo_root / "scripts" / "patchhub" / "static" / "app.js"
    script = rf"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync({json.dumps(str(src_path))}, "utf8");
const nodes = {{
  patchPath: {{ value: "" }},
  issueId: {{ value: "123" }},
  commitMsg: {{ value: "msg" }},
}};
let nowMs = 1000;
const apiCalls = [];
Date.now = () => nowMs;
global.window = globalThis;
global.__ph_w = globalThis;
global.AMP_PATCHHUB_UI = {{}};
global.cfg = {{ paths: {{ patches_root: "patches" }} }};
global.document = {{
  getElementById(id) {{
    return Object.prototype.hasOwnProperty.call(nodes, id) ? nodes[id] : null;
  }},
}};
global.joinRel = (a, b) => {{
  const left = String(a || "").replace(/\/+$/, "");
  const right = String(b || "").replace(/^\/+/, "");
  return left ? left + "/" + right : right;
}};
global.apiGet = (url) => {{
  apiCalls.push(String(url));
  return Promise.resolve({{ ok: true, exists: true }});
}};
global.validateAndPreview = () => {{}};
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
    proc = subprocess.run(
        [node, "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def test_missing_patch_check_skips_empty_path_requests() -> None:
    result = _run_node_scenario(
        """
tickMissingPatchClear({ mode: "idle" });
await flush();
process.stdout.write(JSON.stringify({ calls: apiCalls }));
"""
    )
    assert result["calls"] == []
