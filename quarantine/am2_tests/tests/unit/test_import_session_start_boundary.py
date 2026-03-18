"""User-facing session start boundary for explicit resume/new intent."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
start_user_facing_session = import_module(
    "plugins.import.engine_session_start_boundary"
).start_user_facing_session


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, dict[str, Path]]:
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
    return ImportWizardEngine(resolver=resolver), roots


def _write_inbox_source_dir(roots: dict[str, Path], rel_dir: str) -> None:
    d = roots["inbox"] / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "file.txt").write_text("x", encoding="utf-8")


def test_user_facing_start_requires_explicit_intent_on_conflict(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "src")

    created = engine.create_session("inbox", "src", mode="stage")
    assert created["session_id"]

    conflict = start_user_facing_session(
        engine=engine,
        root="inbox",
        relative_path="src",
        mode="stage",
        intent=None,
    )

    assert conflict["error"]["code"] == "SESSION_START_CONFLICT"
    meta = conflict["error"]["details"][0]["meta"]
    assert meta["session_id"] == created["session_id"]
    assert meta["root"] == "inbox"
    assert meta["relative_path"] == "src"
    assert meta["mode"] == "stage"


def test_user_facing_start_new_deletes_existing_session_dir_before_recreate(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "src")

    created = engine.create_session("inbox", "src", mode="stage")
    session_id = str(created["session_id"])
    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    marker = session_dir / "marker.txt"
    marker.write_text("old", encoding="utf-8")

    recreated = start_user_facing_session(
        engine=engine,
        root="inbox",
        relative_path="src",
        mode="stage",
        intent="new",
    )

    assert recreated["session_id"] == session_id
    assert recreated["current_step_id"] == created["current_step_id"]
    assert not marker.exists()
    state_doc = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
    assert state_doc["session_id"] == session_id
    assert state_doc["status"] == "in_progress"
