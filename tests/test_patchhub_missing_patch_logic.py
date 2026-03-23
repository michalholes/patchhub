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
    src_path = REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_patch_watchdog.js"
    script = rf"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync({json.dumps(str(src_path))}, "utf8");
const registry = new Map();
const nodes = {{
  patchPath: {{ value: "" }},
  issueId: {{ value: "123" }},
  commitMsg: {{ value: "msg" }},
}};
let nowMs = 1000;
const apiCalls = [];
Date.now = () => nowMs;
global.window = globalThis;
global.PH = {{
  register(name, exports) {{ registry.set(String(name), exports || {{}}); }},
  call(name, ...args) {{
    for (const exports of registry.values()) {{
      if (exports && typeof exports[name] === "function") return exports[name](...args);
    }}
    return null;
  }},
  has(name) {{
    for (const exports of registry.values()) {{
      if (exports && typeof exports[name] === "function") return true;
    }}
    return false;
  }},
}};
global.cfg = {{ paths: {{ patches_root: "patches", upload_dir: "patches/incoming" }} }};
global.document = {{
  getElementById(id) {{
    return Object.prototype.hasOwnProperty.call(nodes, id) ? nodes[id] : null;
  }},
}};
global.el = (id) => document.getElementById(id);
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
        cwd=REPO_ROOT,
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
window.PH.call("tickMissingPatchClear", { mode: "idle" });
await flush();
process.stdout.write(JSON.stringify({ calls: apiCalls }));
"""
    )
    assert result["calls"] == []
