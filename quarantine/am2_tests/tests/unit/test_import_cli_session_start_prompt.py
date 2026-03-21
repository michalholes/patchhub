"""Interactive CLI launcher must prompt for resume/new on session conflict."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

cli_renderer = import_module("plugins.import.cli_renderer")
run_launcher = cli_renderer.run_launcher
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, ConfigResolver]:
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
        "plugins": {
            "import": {
                "cli": {
                    "launcher_mode": "interactive",
                    "default_root": "inbox",
                    "default_path": "src",
                    "noninteractive": False,
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


def test_interactive_launcher_prompts_for_new_when_session_exists(
    tmp_path: Path, monkeypatch
) -> None:
    engine, resolver = _make_engine(tmp_path)
    src_dir = tmp_path / "inbox" / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "file.txt").write_text("x", encoding="utf-8")

    created = engine.create_session("inbox", "src", mode="stage")
    session_dir = tmp_path / "wizards" / "import" / "sessions" / str(created["session_id"])
    marker = session_dir / "marker.txt"
    marker.write_text("old", encoding="utf-8")

    seen: dict[str, str] = {}

    def _fake_render_loop(**kwargs):
        seen["session_id"] = kwargs["session_id"]
        state = engine.get_state(kwargs["session_id"])
        seen["created_at"] = str(state.get("created_at") or "")
        return 0

    monkeypatch.setattr(cli_renderer, "_render_loop", _fake_render_loop)

    inputs = iter(["", "", "2"])
    printed: list[str] = []

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=lambda _prompt: next(inputs),
        print_fn=printed.append,
    )

    assert rc == 0
    assert seen["session_id"] == created["session_id"]
    assert not marker.exists()
    joined = "\n".join(printed)
    assert "Existing session detected" in joined
    assert "Start new session" in joined
