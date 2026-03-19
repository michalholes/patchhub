"""Issue 270: WizardDefinition deterministic Draft/Active/History lifecycle."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

fingerprint_json = import_module("plugins.import.fingerprints").fingerprint_json
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
build_router = import_module("plugins.import.ui_api").build_router

wizard_storage = import_module("plugins.import.wizard_editor_storage")

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


def _make_engine(tmp_path: Path) -> ImportWizardEngine:
    roots = {
        "inbox": tmp_path / "inbox",
        "stage": tmp_path / "stage",
        "outbox": tmp_path / "outbox",
        "jobs": tmp_path / "jobs",
        "config": tmp_path / "config",
        "wizards": tmp_path / "wizards",
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


def test_put_draft_does_not_change_active(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()

    active0 = wizard_storage.ensure_wizard_definition_active_exists(fs)
    assert active0.get("version") == 3

    d = dict(active0)
    nodes = []
    for index, node_any in enumerate(active0.get("nodes") or []):
        node = dict(node_any) if isinstance(node_any, dict) else {}
        op = dict(node.get("op") or {})
        inputs = dict(op.get("inputs") or {})
        if index == 0:
            help_text = str(inputs.get("help") or "")
            inputs["help"] = f"{help_text} edited".strip()
        op["inputs"] = inputs
        node["op"] = op
        nodes.append(node)
    d["nodes"] = nodes

    out = wizard_storage.put_wizard_definition_draft(fs, d)
    assert out.get("version") == 3

    active1 = wizard_storage.ensure_wizard_definition_active_exists(fs)
    assert fingerprint_json(active1) == fingerprint_json(active0)


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_rollback_endpoint_returns_v3(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    base = client.get("/import/ui/wizard-definition").json()["definition"]
    assert base.get("version") == 3
    d1 = dict(base)
    nodes = []
    for index, node_any in enumerate(base.get("nodes") or []):
        node = dict(node_any) if isinstance(node_any, dict) else {}
        op = dict(node.get("op") or {})
        inputs = dict(op.get("inputs") or {})
        if index == 0:
            help_text = str(inputs.get("help") or "")
            inputs["help"] = f"{help_text} rollback".strip()
        op["inputs"] = inputs
        node["op"] = op
        nodes.append(node)
    d1["nodes"] = nodes

    assert (
        client.post("/import/ui/wizard-definition", json={"definition": d1}).status_code
        == 200
    )
    assert (
        client.post("/import/ui/wizard-definition/activate", json={}).status_code == 200
    )

    hist = client.get("/import/ui/wizard-definition/history").json()["items"]
    rid = str(hist[0]["id"])

    rb = client.post("/import/ui/wizard-definition/rollback", json={"id": rid})
    assert rb.status_code == 200
    out = rb.json()["definition"]
    assert out.get("version") == 3
