from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


class TestPatchhubLiveUiDebugRender(unittest.TestCase):
    def test_debug_human_formatter_emits_non_empty_reply_control_and_unknown_lines(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = (
            repo_root / "scripts" / "patchhub" / "static" / "patchhub_live_ui.js"
        )
        node_script = f"""
const fs = require('fs');
const vm = require('vm');
global.window = {{
  AMP_PATCHHUB_UI: {{}},
  PH: {{ register() {{}} }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}} }},
}};
global.document = {{ getElementById() {{ return null; }} }};
global.fetch = () => Promise.reject(new Error('unused'));
vm.runInThisContext(fs.readFileSync({json.dumps(str(script_path))}, 'utf8'));
const ui = global.window.AMP_PATCHHUB_UI;
ui.setLiveLevel('debug_human');
const lines = {{
  reply: ui.formatLiveEvent({{
    type: 'reply',
    cmd: 'ready',
    cmd_id: 'patchhub_ready',
    ok: true,
    data: {{ ready: true }},
  }}),
  control: ui.formatLiveEvent({{
    type: 'control',
    event: 'connected',
    seq: 7,
  }}),
  unknown: ui.formatLiveEvent({{
    type: 'mystery',
    foo: 'bar',
  }}),
}};
process.stdout.write(JSON.stringify(lines));
"""
        cp = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        lines = json.loads(cp.stdout)
        self.assertIn("REPLY cmd=ready", lines["reply"])
        self.assertIn("CONTROL event=connected", lines["control"])
        self.assertIn("JSON", lines["unknown"])
        self.assertNotEqual(lines["reply"].strip(), "")
        self.assertNotEqual(lines["control"].strip(), "")
        self.assertNotEqual(lines["unknown"].strip(), "")

    def test_debug_raw_formatter_returns_json_lines(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = (
            repo_root / "scripts" / "patchhub" / "static" / "patchhub_live_ui.js"
        )
        node_script = f"""
const fs = require('fs');
const vm = require('vm');
global.window = {{
  AMP_PATCHHUB_UI: {{}},
  PH: {{ register() {{}} }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}} }},
}};
global.document = {{ getElementById() {{ return null; }} }};
global.fetch = () => Promise.reject(new Error('unused'));
vm.runInThisContext(fs.readFileSync({json.dumps(str(script_path))}, 'utf8'));
const ui = global.window.AMP_PATCHHUB_UI;
ui.setLiveLevel('debug_raw');
const line = ui.formatLiveEvent({{
  type: 'log',
  stage: 'GATE_PYTEST',
  kind: 'SUBPROCESS_STDOUT',
  sev: 'DEBUG',
  ch: 'DETAIL',
  msg: 'tail',
}});
process.stdout.write(JSON.stringify({{ line }}));
"""
        cp = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(cp.stdout)
        self.assertIn('"type":"log"', payload["line"])
        self.assertIn('"kind":"SUBPROCESS_STDOUT"', payload["line"])
        self.assertIn('"msg":"tail"', payload["line"])
