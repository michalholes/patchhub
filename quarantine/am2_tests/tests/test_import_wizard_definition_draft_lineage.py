"""Issue 117: WizardDefinition draft lineage prevents stale editor shadowing."""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from pathlib import Path

import pytest

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
build_router = import_module("plugins.import.ui_api").build_router
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
read_json = import_module("plugins.import.storage").read_json
build_default_wizard_definition_v3 = import_module(
    "plugins.import.dsl.default_wizard_v3"
).build_default_wizard_definition_v3
fingerprint_json = import_module("plugins.import.fingerprints").fingerprint_json
wizard_storage = import_module("plugins.import.wizard_editor_storage")
RootName = import_module("plugins.file_io.service.types").RootName

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
        name: tmp_path / name
        for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
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


def _set_active_v3(engine: ImportWizardEngine) -> tuple[object, dict[str, object]]:
    fs = engine.get_file_service()
    wd = build_default_wizard_definition_v3()
    wizard_storage.save_wizard_definition(fs, wd)
    active = wizard_storage.load_wizard_definition(fs)
    return fs, active


def test_reset_draft_uses_active_v3_not_v2_default(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs, active_v3 = _set_active_v3(engine)

    draft = wizard_storage.reset_wizard_definition_draft(fs)

    assert draft["version"] == 3
    assert fingerprint_json(draft) == fingerprint_json(active_v3)
    meta = read_json(
        fs, RootName.WIZARDS, wizard_storage.WIZARD_DEFINITION_DRAFT_META_REL_PATH
    )
    assert meta == {"source_active_fingerprint": fingerprint_json(active_v3)}


def test_get_quarantines_legacy_draft_that_shadows_v3_active(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs, active_v3 = _set_active_v3(engine)

    stale_v2 = deepcopy(wizard_storage.DEFAULT_WIZARD_DEFINITION)
    atomic_write_json(
        fs,
        RootName.WIZARDS,
        wizard_storage.WIZARD_DEFINITION_DRAFT_REL_PATH,
        stale_v2,
    )

    loaded = wizard_storage.get_wizard_definition_draft(fs)

    assert loaded["version"] == 3
    assert fingerprint_json(loaded) == fingerprint_json(active_v3)
    assert not fs.exists(
        RootName.WIZARDS, wizard_storage.WIZARD_DEFINITION_DRAFT_REL_PATH
    )
    assert not fs.exists(
        RootName.WIZARDS, wizard_storage.WIZARD_DEFINITION_DRAFT_META_REL_PATH
    )
    draft_fp = fingerprint_json(wizard_storage.canonicalize_to_supported(fs, stale_v2))
    active_fp = fingerprint_json(active_v3)
    qdraft, qmeta = wizard_storage._wizard_definition_draft_quarantine_paths(
        source_active_fingerprint=None,
        current_active_fingerprint=active_fp,
        draft_fingerprint=draft_fp,
    )
    assert fs.exists(RootName.WIZARDS, qdraft)
    assert fs.exists(RootName.WIZARDS, qmeta)


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_activate_endpoint_rejects_stale_draft_and_keeps_active_v3(
    tmp_path: Path,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine = _make_engine(tmp_path)
    fs, active_v3 = _set_active_v3(engine)
    stale_v2 = deepcopy(wizard_storage.DEFAULT_WIZARD_DEFINITION)
    atomic_write_json(
        fs,
        RootName.WIZARDS,
        wizard_storage.WIZARD_DEFINITION_DRAFT_REL_PATH,
        stale_v2,
    )

    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    response = client.post("/import/ui/wizard-definition/activate", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    active = wizard_storage.load_wizard_definition(fs)
    assert active["version"] == 3
    assert fingerprint_json(active) == fingerprint_json(active_v3)


def test_matching_legacy_draft_without_metadata_seeds_lineage(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs, active_v3 = _set_active_v3(engine)

    atomic_write_json(
        fs,
        RootName.WIZARDS,
        wizard_storage.WIZARD_DEFINITION_DRAFT_REL_PATH,
        active_v3,
    )

    loaded = wizard_storage.get_wizard_definition_draft(fs)

    assert fingerprint_json(loaded) == fingerprint_json(active_v3)
    meta = read_json(
        fs, RootName.WIZARDS, wizard_storage.WIZARD_DEFINITION_DRAFT_META_REL_PATH
    )
    assert meta == {"source_active_fingerprint": fingerprint_json(active_v3)}
