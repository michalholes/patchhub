from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver
from audiomason.core.logging import VerbosityLevel, get_verbosity, set_verbosity

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
import_cli_main = import_module("plugins.import.cli").import_cli_main


def _make_engine(tmp_path: Path):
    roots = {
        name: tmp_path / name for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
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
    return ImportWizardEngine(resolver=resolver), resolver, roots


def _write_source(roots: dict[str, Path], rel_dir: str) -> None:
    d = roots["inbox"] / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "file.txt").write_text("x", encoding="utf-8")


def _read_last_json(raw: str) -> dict:
    marker = raw.rfind("\n{")
    if marker == -1:
        marker = raw.find("{")
    return json.loads(raw[marker + 1 :])


def test_wizard_start_conflict_requires_explicit_intent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine, resolver, roots = _make_engine(tmp_path)
    _write_source(roots, "src")
    created = engine.create_session("inbox", "src", mode="stage")

    previous = get_verbosity()
    set_verbosity(VerbosityLevel.QUIET)
    try:
        with pytest.raises(SystemExit) as exc:
            import_cli_main(
                ["wizard", "start", "--root", "inbox", "--path", "src"],
                engine=engine,
                resolver=resolver,
            )
    finally:
        set_verbosity(previous)

    assert exc.value.code == 1
    out = _read_last_json(capsys.readouterr().out)
    assert out["code"] == "session_start_conflict"
    assert out["details"]["session_id"] == created["session_id"]


def test_wizard_start_intent_new_recreates_same_session_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine, resolver, roots = _make_engine(tmp_path)
    _write_source(roots, "src")
    created = engine.create_session("inbox", "src", mode="stage")

    previous = get_verbosity()
    set_verbosity(VerbosityLevel.QUIET)
    try:
        rc = import_cli_main(
            [
                "wizard",
                "start",
                "--root",
                "inbox",
                "--path",
                "src",
                "--intent",
                "new",
            ],
            engine=engine,
            resolver=resolver,
        )
    finally:
        set_verbosity(previous)

    assert rc == 0
    out = _read_last_json(capsys.readouterr().out)
    assert out["session_id"] == created["session_id"]
    assert out["state"]["status"] == "in_progress"
