"""Import CLI nav_ui=inline behavior."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

run_launcher = import_module("plugins.import.cli_renderer").run_launcher
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
build_default_wizard_definition_v3 = import_module(
    "plugins.import.dsl.default_wizard_v3"
).build_default_wizard_definition_v3


def _make_engine(
    tmp_path: Path, *, nav_ui: str
) -> tuple[ImportWizardEngine, ConfigResolver, dict[str, Path]]:
    roots = {
        "inbox": tmp_path / "inbox",
        "stage": tmp_path / "stage",
        "outbox": tmp_path / "outbox",
        "jobs": tmp_path / "jobs",
        "config": tmp_path / "config",
        "wizards": tmp_path / "wizards",
    }
    for p in roots.values():
        p.mkdir(parents=True, exist_ok=True)

    # Provide a minimal directory structure so the first wizard step has selectable items.
    (roots["inbox"] / "Book1").mkdir(parents=True, exist_ok=True)

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
                    "launcher_mode": "fixed",
                    "default_root": "inbox",
                    "default_path": "",
                    "noninteractive": False,
                    "render": {"nav_ui": nav_ui},
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
    return ImportWizardEngine(resolver=resolver), resolver, roots


def _active_wizard_definition_path(roots: dict[str, Path]) -> Path:
    return roots["wizards"] / "import" / "definitions" / "wizard_definition.json"


def _write_active_v3_definition(roots: dict[str, Path]) -> None:
    path = _active_wizard_definition_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_default_wizard_definition_v3()), encoding="utf-8")


def _load_only_session_state(roots: dict[str, Path]) -> dict[str, object]:
    sessions_dir = roots["wizards"] / "import" / "sessions"
    sessions = sorted(p for p in sessions_dir.iterdir() if p.is_dir())
    assert len(sessions) == 1
    return json.loads((sessions[0] / "state.json").read_text(encoding="utf-8"))


def test_nav_ui_inline_bootstraps_v3_default_program(tmp_path: Path) -> None:
    engine, resolver, roots = _make_engine(tmp_path, nav_ui="inline")

    inputs = iter(["all", ":cancel"])

    def _input(prompt: str) -> str:
        if "Action (:next" in prompt:
            raise AssertionError("Action prompt must not be shown for nav_ui=inline")
        return next(inputs)

    printed: list[str] = []

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=_input,
        print_fn=printed.append,
    )

    assert rc == 1

    wizard_definition = json.loads(
        _active_wizard_definition_path(roots).read_text(encoding="utf-8")
    )
    assert wizard_definition["version"] == 3


def test_nav_ui_inline_existing_v3_definition_accepts_cancel_on_second_prompt(
    tmp_path: Path,
) -> None:
    engine, resolver, roots = _make_engine(tmp_path, nav_ui="inline")
    _write_active_v3_definition(roots)

    inputs = iter(["1", ":cancel"])
    prompts: list[str] = []

    def _input(prompt: str) -> str:
        if "Action (:next" in prompt:
            raise AssertionError("Action prompt must not be shown for nav_ui=inline")
        prompts.append(prompt)
        try:
            return next(inputs)
        except StopIteration as exc:
            raise AssertionError(
                f"Launcher requested an unexpected extra prompt after inline cancel: {prompt!r}"
            ) from exc

    printed: list[str] = []

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=_input,
        print_fn=printed.append,
    )

    assert rc == 1
    assert len(prompts) == 2

    state = _load_only_session_state(roots)
    assert state["status"] == "aborted"


def test_nav_ui_inline_existing_v3_definition_cancel_does_not_loop(
    tmp_path: Path,
) -> None:
    engine, resolver, roots = _make_engine(tmp_path, nav_ui="inline")
    _write_active_v3_definition(roots)

    prompts: list[str] = []

    def _input(prompt: str) -> str:
        if "Action (:next" in prompt:
            raise AssertionError("Action prompt must not be shown for nav_ui=inline")
        prompts.append(prompt)
        if len(prompts) > 1:
            raise AssertionError(
                f"Inline cancel did not terminate immediately; extra prompt: {prompt!r}"
            )
        return ":cancel"

    printed: list[str] = []

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=_input,
        print_fn=printed.append,
    )

    assert rc == 1
    assert len(prompts) == 1

    state = _load_only_session_state(roots)
    assert state["status"] == "aborted"
