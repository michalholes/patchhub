"""Issue 111: CLI import bootstraps and runs the default v3 program."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

run_launcher = import_module("plugins.import.cli_renderer").run_launcher
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
read_json = import_module("plugins.import.storage").read_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, ConfigResolver, Path]:
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
                    "default_path": "src",
                    "noninteractive": False,
                    "render": {"confirm_defaults": True, "nav_ui": "prompt"},
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
    return ImportWizardEngine(resolver=resolver), resolver, roots["wizards"]


def _write_source_tree(tmp_path: Path) -> None:
    book_dir = tmp_path / "inbox" / "src" / "Author A" / "Book A"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "track01.mp3").write_text("x", encoding="utf-8")


def test_cli_import_uses_bootstrapped_v3_default_program(tmp_path: Path) -> None:
    _write_source_tree(tmp_path)
    engine, resolver, wizards_root = _make_engine(tmp_path)
    fs = engine.get_file_service()

    assert not fs.exists(RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH)

    printed: list[str] = []

    def _input_fn(prompt: str) -> str:
        return "y" if "Start processing" in prompt else ""

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=_input_fn,
        print_fn=printed.append,
    )

    assert rc == 0
    wizard_definition = read_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH)
    assert wizard_definition["version"] == 3

    session_dirs = sorted((wizards_root / "import" / "sessions").iterdir())
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]
    effective_model = json.loads((session_dir / "effective_model.json").read_text())
    state = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
    assert effective_model["flowmodel_kind"] == "dsl_step_graph_v3"
    assert effective_model["entry_step_id"] == "select_authors"
    assert state["phase"] == 2
    assert state["status"] == "processing"
    assert (session_dir / "job_requests.json").exists()

    joined = "\n".join(printed)
    assert "Step: select_authors" in joined
    assert "Label: Authors" in joined
    assert "Step: select_books" in joined
    assert "Step: effective_author" in joined
    assert "Step: covers_policy" in joined
    assert "Step: final_summary_confirm" in joined
    assert "job_ids:" in joined
    assert '"batch_size": 1' in joined


def test_cli_import_validation_error_does_not_loop(tmp_path: Path) -> None:
    _write_source_tree(tmp_path)
    engine, resolver, _wizards_root = _make_engine(tmp_path)

    prompts: list[str] = []
    printed: list[str] = []

    def _submit_step(
        _session_id: str,
        _step_id: str,
        _payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "selection is required",
                "details": [{"path": "$", "reason": "validation_error", "meta": {}}],
            }
        }

    engine.submit_step = _submit_step  # type: ignore[method-assign]

    def _input_fn(prompt: str) -> str:
        prompts.append(prompt)
        if len(prompts) > 1:
            raise AssertionError(f"CLI looped after validation error: {prompt!r}")
        return ""

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=_input_fn,
        print_fn=printed.append,
    )

    assert rc == 1
    assert len(prompts) == 1
    joined = "\n".join(printed)
    assert '"code": "VALIDATION_ERROR"' in joined
    assert '"message": "selection is required"' in joined
