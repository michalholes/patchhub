"""Issue 112: acceptance coverage for the default v3 CLI import path."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

run_launcher = import_module("plugins.import.cli_renderer").run_launcher
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


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


def test_default_v3_cli_acceptance_keeps_selection_and_plan_state(
    tmp_path: Path,
) -> None:
    _write_source_tree(tmp_path)
    engine, resolver, wizards_root = _make_engine(tmp_path)

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

    session_dirs = sorted((wizards_root / "import" / "sessions").iterdir())
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]

    effective_model = json.loads((session_dir / "effective_model.json").read_text(encoding="utf-8"))
    state = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
    plan = json.loads((session_dir / "plan.json").read_text(encoding="utf-8"))
    job_requests = json.loads((session_dir / "job_requests.json").read_text(encoding="utf-8"))

    assert effective_model["flowmodel_kind"] == "dsl_step_graph_v3"
    assert state["phase"] == 2
    assert state["status"] == "processing"
    assert state["current_step_id"] == "processing"
    assert state["selected_author_ids"]
    assert state["selected_book_ids"]
    assert state["answers"]["final_summary_confirm"]["confirm_start"] is True
    assert state["computed"]["plan_summary"]["files"] == 1
    assert plan["summary"]["selected_books"] == 1
    assert state["vars"]["phase1"]["runtime"]["covers_policy"]["mode"] == "embedded"
    assert state["vars"]["phase1"]["runtime"]["covers_policy"]["choice"] == {
        "kind": "candidate",
        "candidate_id": "embedded:track01.mp3",
        "source_relative_path": "Author A/Book A",
    }
    assert state["vars"]["phase1"]["policy"]["clean_inbox"] == "ask"
    assert state["vars"]["phase1"]["policy"]["root_audio_baseline"]["author"] == "__ROOT_AUDIO__"
    assert state["vars"]["phase1"]["policy"]["root_audio_baseline"]["title"] == "Untitled"
    assert job_requests["actions"][0]["source"] == {
        "relative_path": "Author A/Book A",
        "root": "inbox",
    }
    assert [entry["step_id"] for entry in state["trace"]] == [
        "select_authors",
        "select_books",
        "plan_preview_batch",
        "phase1_runtime_defaults",
        "effective_author",
        "effective_title",
        "effective_author_title",
        "filename_policy_author",
        "filename_policy_title",
        "filename_policy",
        "covers_policy_mode",
        "covers_policy",
        "id3_policy_intro",
        "id3_policy_title",
        "id3_policy_artist",
        "id3_policy_album",
        "id3_policy_album_artist",
        "id3_policy",
        "audio_processing_bitrate",
        "audio_processing_loudnorm",
        "audio_processing_split_chapters",
        "audio_processing",
        "publish_policy",
        "delete_source_policy",
        "conflict_policy",
        "parallelism",
        "final_summary_confirm",
    ]

    joined = "\n".join(printed)
    assert "Step: select_authors" in joined
    assert "Step: select_books" in joined
    assert "Step: effective_author" in joined
    assert "Step: final_summary_confirm" in joined
    assert "job_ids:" in joined
    assert '"batch_size": 1' in joined
