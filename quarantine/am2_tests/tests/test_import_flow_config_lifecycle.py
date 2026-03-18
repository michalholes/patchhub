"""Issue 270: FlowConfig deterministic Draft/Active/History lifecycle."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
RootName = import_module("plugins.file_io.service").RootName
read_json = import_module("plugins.import.storage").read_json

editor_storage = import_module("plugins.import.editor_storage")


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

    active0 = editor_storage.ensure_flow_config_active_exists(fs)
    assert isinstance(active0, dict)

    draft = dict(active0)
    draft["defaults"] = {"marker": 1}

    out = editor_storage.put_flow_config_draft(fs, draft)
    assert (out.get("defaults") or {}).get("marker") == 1

    # ACTIVE must remain unchanged.
    active1 = read_json(fs, RootName.WIZARDS, editor_storage.FLOW_CONFIG_REL_PATH)
    assert (active1.get("defaults") or {}).get("marker") != 1


def test_activate_commits_and_bounded_history(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _ = editor_storage.ensure_flow_config_active_exists(fs)

    # Activate once -> one history snapshot.
    d1 = editor_storage.get_flow_config_draft(fs)
    d1 = dict(d1)
    d1["defaults"] = {"marker": 1}
    editor_storage.put_flow_config_draft(fs, d1)

    a1 = editor_storage.activate_flow_config_draft(fs)
    assert (a1.get("defaults") or {}).get("marker") == 1
    assert not fs.exists(RootName.WIZARDS, editor_storage.FLOW_CONFIG_DRAFT_REL_PATH)

    hist = editor_storage.list_history(fs, kind="flow_config")
    assert len(hist) == 1

    # Repeat activations; history retention is capped at 5.
    for i in range(2, 8):
        d = editor_storage.get_flow_config_draft(fs)
        d = dict(d)
        d["defaults"] = {"marker": i}
        editor_storage.put_flow_config_draft(fs, d)
        editor_storage.activate_flow_config_draft(fs)

    hist2 = editor_storage.list_history(fs, kind="flow_config")
    assert len(hist2) == 5
