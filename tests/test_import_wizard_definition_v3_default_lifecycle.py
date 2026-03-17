"""Issue 111: v3 bootstrap stays opt-in and existing v2 artifacts still dispatch."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
load_or_bootstrap_wizard_definition = import_module(
    "plugins.import.wizard_definition_model"
).load_or_bootstrap_wizard_definition
CANONICAL_STEP_ORDER = import_module("plugins.import.flow_runtime").CANONICAL_STEP_ORDER
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


def _make_engine(tmp_path: Path) -> ImportWizardEngine:
    roots = {
        name: tmp_path / name
        for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
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
                    "render": {"nav_ui": "prompt"},
                }
            }
        },
    }
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver)


def _v2_definition() -> dict[str, object]:
    return {
        "version": 2,
        "graph": {
            "entry_step_id": CANONICAL_STEP_ORDER[0],
            "nodes": [{"step_id": sid} for sid in CANONICAL_STEP_ORDER],
            "edges": [
                {
                    "from_step_id": CANONICAL_STEP_ORDER[i],
                    "to_step_id": CANONICAL_STEP_ORDER[i + 1],
                    "priority": 0,
                    "when": None,
                }
                for i in range(len(CANONICAL_STEP_ORDER) - 1)
            ],
        },
    }


def test_existing_v2_artifact_keeps_v2_dispatch_while_v3_bootstrap_stays_available(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()

    atomic_write_json(
        fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, _v2_definition()
    )

    loaded = load_or_bootstrap_wizard_definition(fs, bootstrap_default_version=3)
    assert loaded["version"] == 2

    flow_model = engine.get_flow_model()
    assert flow_model.get("flowmodel_kind") != "dsl_step_graph_v3"

    state = engine.create_session("inbox", "")
    assert state.get("current_step_id") == "select_authors"


def test_existing_v3_artifact_stays_authoritative_over_bootstrap_seed(
    tmp_path: Path,
) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()

    authored = {
        "version": 3,
        "entry_step_id": "pick_author",
        "nodes": [
            {
                "step_id": "pick_author",
                "op": {
                    "primitive_id": "ui.prompt_text",
                    "primitive_version": 1,
                    "inputs": {"label": "Authored label"},
                    "writes": [],
                },
            }
        ],
        "edges": [],
    }
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, authored)

    loaded = load_or_bootstrap_wizard_definition(fs, bootstrap_default_version=3)

    assert loaded["version"] == 3
    assert loaded["entry_step_id"] == "pick_author"
    assert loaded["nodes"][0]["op"]["inputs"]["label"] == "Authored label"
