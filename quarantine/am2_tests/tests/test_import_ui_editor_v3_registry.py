"""Issue 106: v3 editor registry path uses existing endpoints only."""

from __future__ import annotations

import json
import re
import subprocess
from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
build_router = import_module("plugins.import.ui_api").build_router

_HAS_FASTAPI = True
try:
    import fastapi  # noqa: F401
except Exception:
    _HAS_FASTAPI = False

try:
    import httpx  # noqa: F401

    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False


ALLOWED_UI_ENDPOINTS = {
    "/import/ui/primitive-registry",
    "/import/ui/wizard-definition",
    "/import/ui/wizard-definition/validate",
    "/import/ui/wizard-definition/activate",
    "/import/ui/wizard-definition/reset",
    "/import/ui/wizard-definition/history",
    "/import/ui/wizard-definition/rollback",
}


_NODE_REGISTRY_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");

const calls = [];
const sandbox = {
  window: {
    AM2EditorHTTP: {
      requestJSON(url, options) {
        calls.push({ url, options: options || null });
        return Promise.resolve({ ok: true, data: {} });
      },
    },
  },
  globalThis: {},
  console,
};
sandbox.globalThis = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync("plugins/import/ui/web/assets/dsl_editor/registry_api.js", "utf8"),
  sandbox,
  { filename: "registry_api.js" },
);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const api = sandbox.window.AM2DSLEditorRegistryAPI;
Promise.resolve()
  .then(() => api.validateWizardDefinition(payload.definition))
  .then(() => api.saveWizardDefinition(payload.definition))
  .then(() => {
    process.stdout.write(
      JSON.stringify({
        original: payload.definition,
        calls: calls.map((item) => ({
          url: item.url,
          body: JSON.parse(String((item.options && item.options.body) || "{}")),
        })),
      }),
    );
  })
  .catch((err) => {
    console.error(String(err && err.stack ? err.stack : err));
    process.exit(1);
  });
"""


def _run_node_registry_api(
    payload: dict[str, object], *, timeout: int = 5
) -> dict[str, object]:
    try:
        proc = subprocess.run(
            ["node", "-e", _NODE_REGISTRY_SCRIPT],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as err:
        raise AssertionError("Node registry_api harness timed out") from err
    return json.loads(proc.stdout)


def _make_engine(tmp_path: Path) -> ImportWizardEngine:
    roots = {
        name: tmp_path / name
        for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
    }
    defaults = {
        "file_io": {
            "roots": {
                "inbox_dir": str(roots["inbox"]),
                "stage_dir": str(roots["stage"]),
                "outbox_dir": str(roots["outbox"]),
                "jobs_dir": str(roots["jobs"]),
                "config_dir": str(roots["config"]),
                "wizards_dir": str(roots["wizards"]),
            }
        },
        "output_dir": str(roots["outbox"]),
        "diagnostics": {"enabled": False},
    }
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver)


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_import_ui_v3_registry_endpoint_returns_bootstrapped_primitives(
    tmp_path: Path,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    response = client.get("/import/ui/primitive-registry")
    assert response.status_code == 200
    registry = response.json()["registry"]
    assert registry["registry_version"] == 1
    primitive_ids = {
        str(item.get("primitive_id")) for item in registry.get("primitives", [])
    }
    assert primitive_ids
    assert all(primitive_ids)
    assert "select_authors" not in primitive_ids
    assert {
        "import.phase1_runtime",
        "ui.message",
        "ui.prompt_text",
        "ui.prompt_select",
        "ui.prompt_confirm",
    } <= primitive_ids


def test_v3_registry_api_module_uses_existing_editor_endpoints_only() -> None:
    source = Path("plugins/import/ui/web/assets/dsl_editor/registry_api.js").read_text(
        encoding="utf-8"
    )
    endpoints = set(re.findall(r'"(/import/ui/[^"]+)"', source))
    assert endpoints == ALLOWED_UI_ENDPOINTS


def test_v3_registry_api_strips_editor_metadata_from_wire_payload() -> None:
    out = _run_node_registry_api(
        {
            "definition": {
                "version": 3,
                "entry_step_id": "pick_author",
                "nodes": [
                    {
                        "step_id": "pick_author",
                        "op": {
                            "primitive_id": "ui.prompt_select",
                            "primitive_version": 1,
                            "inputs": {},
                            "writes": [],
                        },
                    }
                ],
                "edges": [],
                "_am2_ui": {
                    "showOptional": True,
                    "dsl_editor": {"selected_library_id": ""},
                },
            }
        }
    )

    assert out["original"]["_am2_ui"]["showOptional"] is True
    assert [item["url"] for item in out["calls"]] == [
        "/import/ui/wizard-definition/validate",
        "/import/ui/wizard-definition",
    ]
    assert all("_am2_ui" not in item["body"]["definition"] for item in out["calls"])
    assert out["calls"][0]["body"]["definition"]["version"] == 3
    assert out["calls"][1]["body"]["definition"]["entry_step_id"] == "pick_author"
