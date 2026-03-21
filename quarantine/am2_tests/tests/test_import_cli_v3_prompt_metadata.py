"""Issue 109: CLI renderer parity for v3 prompt metadata."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

run_launcher = import_module("plugins.import.cli_renderer").run_launcher
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


PROMPT_FLOW = {
    "version": 3,
    "entry_step_id": "ask_name",
    "nodes": [
        {
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {
                    "label": "Display name",
                    "prompt": "Enter the final display name",
                    "help": "CLI and Web must render the same metadata",
                    "hint": "Press Enter to accept the backend prefill",
                    "examples": ["Ada", "Grace"],
                    "prefill": "Ada",
                },
                "writes": [
                    {
                        "to_path": "$.state.answers.ask_name.value",
                        "value": {"expr": "$.op.outputs.value"},
                    }
                ],
            },
        },
        {
            "step_id": "stop",
            "op": {
                "primitive_id": "ctrl.stop",
                "primitive_version": 1,
                "inputs": {},
                "writes": [],
            },
        },
    ],
    "edges": [{"from": "ask_name", "to": "stop"}],
}


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
                    "launcher_mode": "fixed",
                    "default_root": "inbox",
                    "default_path": "",
                    "noninteractive": False,
                    "render": {"confirm_defaults": True},
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


def test_cli_renderer_renders_v3_prompt_metadata_and_accepts_prefill(
    tmp_path: Path,
) -> None:
    engine, resolver = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PROMPT_FLOW)

    printed: list[str] = []
    inputs = iter([""])

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=lambda _prompt: next(inputs),
        print_fn=printed.append,
    )

    assert rc == 0
    joined = "\n".join(printed)
    assert "Label: Display name" in joined
    assert "Prompt: Enter the final display name" in joined
    assert "Help: CLI and Web must render the same metadata" in joined
    assert "Hint: Press Enter to accept the backend prefill" in joined
    assert "Examples:" in joined
    assert "Prefill: Ada" in joined
    assert '"status": "completed"' in joined
    assert '"value": "Ada"' in joined


def test_cli_renderer_prefill_dict_preserves_unicode_rendering() -> None:
    rendered = import_module("plugins.import.cli_renderer")._stringify_prompt_value(
        {
            "author": "Meyrink, Gustav",
            "title": "Obrazy vepsan\u00e9 do vzduchu",
        }
    )

    assert '"title": "Obrazy vepsan\u00e9 do vzduchu"' in rendered
    assert "\\u00e1" not in rendered
    assert "\\u00e9" not in rendered
