"""Import wizard: spec alignment regression tests.

These tests validate alignment with docs/specification.md section 10.
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


def _disable_optional_steps(roots: dict[str, Path]) -> None:
    cfg_path = roots["wizards"] / "import" / "config" / "flow_config.json"
    cfg_any = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg_any["steps"] = {
        "filename_policy": {"enabled": False},
        "covers_policy": {"enabled": False},
        "id3_policy": {"enabled": False},
        "audio_processing": {"enabled": False},
        "publish_policy": {"enabled": False},
        "delete_source_policy": {"enabled": False},
        "parallelism": {"enabled": False},
    }
    cfg_path.write_text(json.dumps(cfg_any), encoding="utf-8")


def _optional_disable_overrides() -> dict[str, object]:
    return {
        "steps": {
            "filename_policy": {"enabled": False},
            "covers_policy": {"enabled": False},
            "id3_policy": {"enabled": False},
            "audio_processing": {"enabled": False},
            "publish_policy": {"enabled": False},
            "delete_source_policy": {"enabled": False},
            "parallelism": {"enabled": False},
        }
    }


def test_flow_model_contains_resolve_conflicts_before_processing(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "book1")

    flow_model = engine.get_flow_model()
    steps = {s.get("step_id"): s for s in flow_model.get("steps", []) if isinstance(s, dict)}
    step_ids = list(steps)

    assert step_ids.count("phase1_runtime_defaults") == 1
    assert step_ids.count("resolve_conflicts_batch") == 1
    assert step_ids.count("processing") == 1
    assert step_ids.index("resolve_conflicts_batch") < step_ids.index("processing")
    assert steps["processing"].get("phase") == 2


def test_step_schemas_match_spec_field_names(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "book1")

    flow_model = engine.get_flow_model()
    steps = {s.get("step_id"): s for s in flow_model.get("steps", []) if isinstance(s, dict)}

    final_writes = [
        w.get("to_path")
        for w in steps["final_summary_confirm"].get("writes", [])
        if isinstance(w, dict)
    ]
    assert "$.state.answers.final_summary_confirm.confirm_start" in final_writes
    assert steps["final_summary_confirm"].get("primitive_id") == "ui.prompt_confirm"

    resolve_writes = [
        w.get("to_path")
        for w in steps["resolve_conflicts_batch"].get("writes", [])
        if isinstance(w, dict)
    ]
    assert resolve_writes == ["$.state.answers.resolve_conflicts_batch.confirm"]


def test_select_books_ok_auto_advances_past_plan_preview(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "book1")

    root = roots["inbox"] / "AuthorA"
    (root / "Book1").mkdir(parents=True, exist_ok=True)
    (root / "Book2").mkdir(parents=True, exist_ok=True)
    ((root / "Book1") / "a.txt").write_text("x", encoding="utf-8")
    ((root / "Book2") / "b.txt").write_text("y", encoding="utf-8")

    state = engine.create_session(
        "inbox",
        "",
        mode="stage",
        flow_overrides=_optional_disable_overrides(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id
    assert state.get("current_step_id") == "select_books"

    state = engine.submit_step(session_id, "select_books", {"selection": "1"})
    assert state.get("current_step_id") == "effective_author"


def test_final_summary_confirm_uses_confirm_start_gate(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "book1")

    flow_model = engine.get_flow_model()
    steps = {s.get("step_id"): s for s in flow_model.get("steps", []) if isinstance(s, dict)}

    final_step = steps["final_summary_confirm"]
    final_writes = [w.get("to_path") for w in final_step.get("writes", []) if isinstance(w, dict)]
    assert final_step.get("primitive_id") == "ui.prompt_confirm"
    assert final_writes == ["$.state.answers.final_summary_confirm.confirm_start"]
