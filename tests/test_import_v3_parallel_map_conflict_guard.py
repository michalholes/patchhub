"""Issue 105 corrective: parallel.map@1 only fails on conflicting writes."""

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


PARALLEL_MAP_WITH_CONFLICTING_WRITES = {
    "version": 3,
    "entry_step_id": "map_step",
    "nodes": [
        {
            "step_id": "map_step",
            "op": {
                "primitive_id": "parallel.map",
                "primitive_version": 1,
                "inputs": {"items": [1], "merge_mode": "fail_on_conflict"},
                "writes": [
                    {"to_path": "$.state.vars.value", "value": 1},
                    {"to_path": "$.state.vars.value", "value": 2},
                ],
            },
        }
    ],
    "edges": [],
}

PARALLEL_MAP_WITH_NON_CONFLICTING_WRITES = {
    "version": 3,
    "entry_step_id": "map_step",
    "nodes": [
        {
            "step_id": "map_step",
            "op": {
                "primitive_id": "parallel.map",
                "primitive_version": 1,
                "inputs": {"items": [1], "merge_mode": "fail_on_conflict"},
                "writes": [
                    {"to_path": "$.state.vars.first", "value": 1},
                    {"to_path": "$.state.vars.second", "value": 2},
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
    "edges": [{"from": "map_step", "to": "stop"}],
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


def test_parallel_map_conflicting_writes_fail_with_invariant_violation(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs,
        RootName.WIZARDS,
        WIZARD_DEFINITION_REL_PATH,
        PARALLEL_MAP_WITH_CONFLICTING_WRITES,
    )

    state = engine.create_session("inbox", "")

    assert state["error"]["code"] == "INVARIANT_VIOLATION"
    assert state["error"]["message"] == "parallel_map_conflicting_writes"


def test_parallel_map_non_conflicting_writes_apply_without_blanket_invariant(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(
        fs,
        RootName.WIZARDS,
        WIZARD_DEFINITION_REL_PATH,
        PARALLEL_MAP_WITH_NON_CONFLICTING_WRITES,
    )

    state = engine.create_session("inbox", "")

    assert state["status"] == "completed"
    assert state.get("error") is None
    assert state["vars"] == {"first": 1, "second": 2}
