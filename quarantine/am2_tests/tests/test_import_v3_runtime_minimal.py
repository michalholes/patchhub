"""Issue 149: minimal v3 runtime flow for import.phase1_runtime."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


MINIMAL_V3 = {
    "version": 3,
    "entry_step_id": "phase1_runtime_defaults",
    "nodes": [
        {
            "step_id": "phase1_runtime_defaults",
            "op": {
                "primitive_id": "import.phase1_runtime",
                "primitive_version": 1,
                "inputs": {},
                "writes": [
                    {
                        "to_path": "$.state.vars.phase1.runtime",
                        "value": {"expr": "$.op.outputs.snapshot"},
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
    "edges": [{"from": "phase1_runtime_defaults", "to": "stop"}],
}


def _make_engine(tmp_path: Path) -> ImportWizardEngine:
    roots = {
        "inbox": tmp_path / "inbox",
        "stage": tmp_path / "stage",
        "outbox": tmp_path / "outbox",
        "jobs": tmp_path / "jobs",
        "config": tmp_path / "config",
        "wizards": tmp_path / "wizards",
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
    return ImportWizardEngine(resolver=resolver)


def test_v3_runtime_runs_phase1_runtime_then_ctrl_stop(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, MINIMAL_V3)

    state = engine.create_session("inbox", "")

    assert state["status"] == "completed"
    assert state["current_step_id"] == "stop"
    assert state["cursor"]["step_id"] == "stop"
    assert state["answers"] == {}
    assert state["inputs"] == {}
    assert [entry["step_id"] for entry in state["trace"]] == [
        "phase1_runtime_defaults",
        "stop",
    ]
    assert [entry["result"] for entry in state["trace"]] == ["OK", "OK"]
    assert state["vars"]["phase1"]["runtime"]["effective_author_title"] == {
        "author": "",
        "title": "",
    }
    assert state["vars"]["phase1"]["runtime"]["parallelism"] == {"workers": 1}

    blocked = engine.apply_action(state["session_id"], "next")
    assert blocked["error"]["code"] == "INVARIANT_VIOLATION"


def test_phase1_runtime_uses_registry_dispatch_only() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    interpreter_text = (
        repo_root / "plugins" / "import" / "dsl" / "interpreter_v3.py"
    ).read_text(encoding="utf-8")
    intake_text = (
        repo_root / "plugins" / "import" / "phase1_source_intake.py"
    ).read_text(encoding="utf-8")

    assert "execute_import_phase1_primitive" not in interpreter_text
    assert "_is_phase1_runtime_primitive" not in interpreter_text
    assert "build_runtime_snapshot" not in intake_text


def test_phase1_projection_runtime_refreshes_current_answers() -> None:
    build_phase1_projection = import_module(
        "plugins.import.phase1_source_intake"
    ).build_phase1_projection

    discovery = [
        {"kind": "dir", "relative_path": "AuthorA/Book1"},
        {"kind": "file", "relative_path": "AuthorA/Book1/track.mp3"},
    ]
    state = {
        "source": {"root": "inbox", "relative_path": ""},
        "answers": {
            "final_summary_confirm": {"confirm_start": True},
            "conflict_policy": {"mode": "skip"},
        },
        "computed": {"plan_summary": {"selected_count": 1}},
        "conflicts": {"present": False, "items": []},
    }

    out = build_phase1_projection(discovery=discovery, state=state)

    assert out["runtime"]["final_summary_confirm"] == {"confirm_start": True}
    assert out["runtime"]["conflict_policy"] == {"mode": "skip"}
    assert out["runtime"]["plan_preview_batch"]["summary"] == {"selected_count": 1}
