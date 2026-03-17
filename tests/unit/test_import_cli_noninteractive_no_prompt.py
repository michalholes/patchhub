"""CLI noninteractive mode must not prompt for input."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

run_launcher = import_module("plugins.import.cli_renderer").run_launcher
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, ConfigResolver]:
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
        "plugins": {
            "import": {
                "cli": {
                    "launcher_mode": "interactive",
                    "default_root": "",
                    "default_path": "",
                    "noninteractive": True,
                }
            }
        },
    }
    resolver = ConfigResolver(
        cli_args={},
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver), resolver


def test_noninteractive_requires_root_and_path_and_does_not_prompt(
    tmp_path: Path,
) -> None:
    engine, resolver = _make_engine(tmp_path)

    def _input(_prompt: str) -> str:
        raise AssertionError("input() must not be called in noninteractive mode")

    printed: list[str] = []

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=_input,
        print_fn=printed.append,
    )

    assert rc == 1
    assert any("noninteractive" in line for line in printed)


def test_noninteractive_conflict_requires_explicit_intent_and_does_not_prompt(
    tmp_path: Path,
) -> None:
    engine, resolver = _make_engine(tmp_path)
    roots = {
        "inbox": tmp_path / "inbox",
        "wizards": tmp_path / "wizards",
    }
    src_dir = roots["inbox"] / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "file.txt").write_text("x", encoding="utf-8")
    created = engine.create_session("inbox", "src", mode="stage")
    assert created["session_id"]

    def _input(_prompt: str) -> str:
        raise AssertionError("input() must not be called in noninteractive mode")

    printed: list[str] = []

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={"root": "inbox", "path": "src"},
        input_fn=_input,
        print_fn=printed.append,
    )

    assert rc == 1
    assert any("SESSION_START_CONFLICT" in line for line in printed)
