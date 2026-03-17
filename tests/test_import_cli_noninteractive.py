"""Issue 219: CLI noninteractive launcher must never prompt.

Noninteractive requires root, relative_path may be empty.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

resolve_launcher_inputs = import_module(
    "plugins.import.cli_launcher_facade"
).resolve_launcher_inputs
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


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


class _Cfg:
    def __init__(self) -> None:
        self.launcher_mode = "interactive"
        self.default_root = "inbox"
        self.default_path = ""
        self.noninteractive = True
        self.confirm_defaults = True
        self.max_list_items = 50


def test_noninteractive_allows_empty_path_and_does_not_prompt(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)

    def _input(_prompt: str) -> str:
        raise AssertionError("input() must not be called in noninteractive mode")

    printed: list[str] = []

    ok, root, rel, err = resolve_launcher_inputs(
        engine=engine,
        cfg=_Cfg(),
        input_fn=_input,
        print_fn=printed.append,
    )

    assert err == ""
    assert ok is True
    assert root == "inbox"
    assert rel == ""
