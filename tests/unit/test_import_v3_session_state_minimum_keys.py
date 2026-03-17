"""Issue 105: SessionState minimum keys and backward-compatible upgrade."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
append_trace_event = import_module("plugins.import.engine_util").append_trace_event
sync_session_cursor = import_module("plugins.import.engine_util").sync_session_cursor
_ensure_session_state_fields = import_module(
    "plugins.import.engine_util"
)._ensure_session_state_fields
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


MINIMAL_V3 = {
    "version": 3,
    "entry_step_id": "hello",
    "nodes": [
        {
            "step_id": "hello",
            "op": {
                "primitive_id": "ui.message",
                "primitive_version": 1,
                "inputs": {},
                "writes": [],
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
    "edges": [{"from": "hello", "to": "stop"}],
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


def test_create_session_v3_contains_minimum_keys(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, MINIMAL_V3)

    state = engine.create_session("inbox", "")

    assert state["session_state_version"] == 1
    assert isinstance(state["cursor"], dict)
    assert state["cursor"]["step_id"] == state["current_step_id"]
    assert isinstance(state["answers"], dict)
    assert isinstance(state["vars"], dict)
    assert isinstance(state["jobs"], dict)
    assert state["jobs"]["emitted"] == []
    assert state["jobs"]["submitted"] == []
    assert isinstance(state["trace"], list)


def test_ensure_session_state_fields_upgrades_legacy_state() -> None:
    state = {"current_step_id": "hello", "inputs": {"hello": {"value": "x"}}}
    out = _ensure_session_state_fields(state)
    sync_session_cursor(out)

    assert out["session_state_version"] == 1
    assert out["answers"] == {"hello": {"value": "x"}}
    assert out["cursor"]["step_id"] == "hello"
    assert out["vars"] == {}
    assert out["jobs"] == {"emitted": [], "submitted": []}


def test_append_trace_event_keeps_only_last_1000_events() -> None:
    state = {"trace": []}

    for index in range(1005):
        append_trace_event(
            state,
            {
                "step_id": f"step_{index}",
                "primitive_id": "ui.message",
                "primitive_version": 1,
                "result": "OK",
                "writes": [],
            },
        )

    trace = state["trace"]
    assert len(trace) == 1000
    assert trace[0]["step_id"] == "step_5"
    assert trace[-1]["step_id"] == "step_1004"
    assert trace[0]["seq"] == 1
    assert trace[-1]["seq"] == 1000
