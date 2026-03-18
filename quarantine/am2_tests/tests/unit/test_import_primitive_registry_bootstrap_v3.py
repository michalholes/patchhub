"""Issue 105: primitive registry bootstrap for baseline v3 primitives."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
load_or_bootstrap_primitive_registry = import_module(
    "plugins.import.dsl.primitive_registry_storage"
).load_or_bootstrap_primitive_registry
save_primitive_registry = import_module(
    "plugins.import.dsl.primitive_registry_storage"
).save_primitive_registry


BASELINE_IDS = {
    ("ui.message", 1),
    ("ui.prompt_text", 1),
    ("ui.prompt_select", 1),
    ("ui.prompt_confirm", 1),
    ("ctrl.if", 1),
    ("ctrl.switch", 1),
    ("ctrl.guard", 1),
    ("ctrl.stop", 1),
    ("data.set", 1),
    ("data.unset", 1),
    ("data.filter", 1),
    ("data.map", 1),
    ("data.group_by", 1),
    ("data.sort", 1),
    ("data.format", 1),
    ("io.list", 1),
    ("io.stat", 1),
    ("io.read_meta", 1),
    ("import.phase1_runtime", 1),
    ("job.emit", 1),
    ("job.submit", 1),
    ("parallel.map", 1),
    ("parallel.fork_join", 1),
    ("flow.invoke", 1),
    ("flow.loop", 1),
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


def test_load_or_bootstrap_primitive_registry_uses_baseline_ids(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    registry = load_or_bootstrap_primitive_registry(engine.get_file_service())

    primitives = registry.get("primitives")
    assert registry["registry_version"] == 1
    assert isinstance(primitives, list)

    got = {
        (str(item.get("primitive_id")), int(item.get("version")))
        for item in primitives
        if isinstance(item, dict)
        and isinstance(item.get("primitive_id"), str)
        and isinstance(item.get("version"), int)
    }
    assert len(got) == len(primitives)
    assert BASELINE_IDS.issubset(got)
    assert ("select_books", 1) not in got


def test_existing_registry_artifact_keeps_custom_entries_and_gains_baseline_ids(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()

    save_primitive_registry(
        fs,
        {
            "registry_version": 1,
            "primitives": [
                {
                    "primitive_id": "custom.prompt",
                    "version": 1,
                    "phase": 1,
                    "inputs_schema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                    "outputs_schema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                    "allowed_errors": [],
                }
            ],
        },
    )

    loaded = load_or_bootstrap_primitive_registry(fs)

    got = {
        (str(item.get("primitive_id")), int(item.get("version")))
        for item in loaded["primitives"]
        if isinstance(item, dict)
        and isinstance(item.get("primitive_id"), str)
        and isinstance(item.get("version"), int)
    }
    assert ("custom.prompt", 1) in got
    assert BASELINE_IDS.issubset(got)
    assert len(got) == len(loaded["primitives"])
