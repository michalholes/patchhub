"""Import plugin: session identity and snapshot isolation tests.

These tests validate deterministic behavior and snapshot semantics for the
import wizard engine.
"""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, dict[str, Path]]:
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
    cli_args = defaults
    resolver = ConfigResolver(
        cli_args=cli_args,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver), roots


def _write_inbox_source_dir(roots: dict[str, Path], rel_dir: str) -> None:
    d = roots["inbox"] / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "file.txt").write_text("x", encoding="utf-8")


def test_session_id_differs_by_mode(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "book1")

    s_stage = engine.create_session("inbox", "book1", mode="stage")
    s_inplace = engine.create_session("inbox", "book1", mode="inplace")

    assert s_stage.get("session_id")
    assert s_inplace.get("session_id")
    assert s_stage["session_id"] != s_inplace["session_id"]


def test_snapshot_isolation_for_effective_files(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "book2")

    state = engine.create_session("inbox", "book2", mode="stage")
    session_id = str(state.get("session_id") or "")
    assert session_id

    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    eff_model_path = session_dir / "effective_model.json"
    eff_cfg_path = session_dir / "effective_config.json"
    assert eff_model_path.exists()
    assert eff_cfg_path.exists()

    eff_model_before = eff_model_path.read_text(encoding="utf-8")
    eff_cfg_before = eff_cfg_path.read_text(encoding="utf-8")

    # Mutate active wizard definition/config after the session was created.
    wizard_path = roots["wizards"] / "import" / "definitions" / "wizard_definition.json"
    cfg_path = roots["wizards"] / "import" / "config" / "flow_config.json"

    wizard_any = json.loads(wizard_path.read_text(encoding="utf-8"))
    wizard_any["flow_id"] = "mutated_flow_id"
    wizard_path.write_text(json.dumps(wizard_any), encoding="utf-8")

    cfg_any = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg_any["ui"] = {"_test_mutation": True}
    cfg_path.write_text(json.dumps(cfg_any), encoding="utf-8")

    # Resume via state read: frozen effective artifacts must not change.
    loaded = engine.get_state(session_id)
    assert loaded.get("session_id") == session_id

    assert eff_model_path.read_text(encoding="utf-8") == eff_model_before
    assert eff_cfg_path.read_text(encoding="utf-8") == eff_cfg_before
