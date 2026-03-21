"""Issue 113: deterministic v2/v3 coexistence with the v3 default bootstrap."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
read_json = import_module("plugins.import.storage").read_json
CANONICAL_STEP_ORDER = import_module("plugins.import.flow_runtime").CANONICAL_STEP_ORDER
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


def _make_engine(
    tmp_path: Path,
    *,
    launcher_mode: str = "fixed",
    noninteractive: bool = False,
    nav_ui: str = "prompt",
) -> tuple[ImportWizardEngine, dict[str, Path]]:
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
                    "launcher_mode": launcher_mode,
                    "default_root": "inbox",
                    "default_path": "",
                    "noninteractive": noninteractive,
                    "render": {"nav_ui": nav_ui},
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
    return ImportWizardEngine(resolver=resolver), roots


def _write_source_tree(roots: dict[str, Path], *, relative_path: str = "src") -> None:
    book_dir = roots["inbox"] / relative_path / "Author A" / "Book A"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "track01.mp3").write_text("x", encoding="utf-8")


def _v2_definition() -> dict[str, object]:
    return {
        "version": 2,
        "graph": {
            "entry_step_id": CANONICAL_STEP_ORDER[0],
            "nodes": [{"step_id": step_id} for step_id in CANONICAL_STEP_ORDER],
            "edges": [
                {
                    "from_step_id": CANONICAL_STEP_ORDER[index],
                    "to_step_id": CANONICAL_STEP_ORDER[index + 1],
                    "priority": 0,
                    "when": None,
                }
                for index in range(len(CANONICAL_STEP_ORDER) - 1)
            ],
        },
    }


def test_v2_and_v3_sessions_can_coexist_deterministically(tmp_path: Path) -> None:
    engine, roots = _make_engine(
        tmp_path,
        launcher_mode="disabled",
        noninteractive=True,
        nav_ui="both",
    )
    _write_source_tree(roots)

    state_v3 = engine.create_session("inbox", "src")
    assert state_v3["session_id"]
    assert state_v3["current_step_id"] == "select_authors"

    state_v3_loaded = engine.get_state(str(state_v3["session_id"]))
    assert state_v3_loaded["effective_model"]["flowmodel_kind"] == "dsl_step_graph_v3"

    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, _v2_definition())

    state_v2 = engine.create_session("inbox", "src")
    assert state_v2["session_id"] != state_v3["session_id"]
    assert state_v2["current_step_id"] == "select_authors"

    state_v2_loaded = engine.get_state(str(state_v2["session_id"]))
    assert state_v2_loaded["effective_model"].get("flowmodel_kind") != "dsl_step_graph_v3"

    state_v3_reloaded = engine.get_state(str(state_v3["session_id"]))
    assert state_v3_reloaded["effective_model"]["flowmodel_kind"] == "dsl_step_graph_v3"


def test_default_selection_policy_is_missing_means_v3_and_explicit_v2_wins(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(
        tmp_path,
        launcher_mode="fixed",
        noninteractive=False,
        nav_ui="prompt",
    )
    _write_source_tree(roots, relative_path="v3_default")
    _write_source_tree(roots, relative_path="v2_explicit")
    _write_source_tree(roots, relative_path="v3_default_again")

    state_default_v3 = engine.create_session("inbox", "v3_default")
    loaded_default_v3 = engine.get_state(str(state_default_v3["session_id"]))
    assert loaded_default_v3["effective_model"]["flowmodel_kind"] == "dsl_step_graph_v3"

    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, _v2_definition())

    state_explicit_v2 = engine.create_session("inbox", "v2_explicit")
    loaded_explicit_v2 = engine.get_state(str(state_explicit_v2["session_id"]))
    assert loaded_explicit_v2["effective_model"].get("flowmodel_kind") != "dsl_step_graph_v3"

    fs.delete_file(RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH)

    state_default_v3_again = engine.create_session("inbox", "v3_default_again")
    loaded_default_v3_again = engine.get_state(str(state_default_v3_again["session_id"]))
    assert loaded_default_v3_again["effective_model"]["flowmodel_kind"] == "dsl_step_graph_v3"


def test_session_snapshot_stays_frozen_without_legacy_json(tmp_path: Path) -> None:
    engine, roots = _make_engine(
        tmp_path,
        launcher_mode="disabled",
        noninteractive=True,
        nav_ui="both",
    )
    _write_source_tree(roots, relative_path="snapshot_case")

    state = engine.create_session("inbox", "snapshot_case")
    session_id = str(state["session_id"])
    fs = engine.get_file_service()
    session_dir = f"import/sessions/{session_id}"

    assert not fs.exists(RootName.WIZARDS, "import/catalog/catalog.json")
    assert not fs.exists(RootName.WIZARDS, "import/flow/current.json")

    snapshot_before = read_json(fs, RootName.WIZARDS, f"{session_dir}/effective_model.json")
    flow_cfg = read_json(fs, RootName.WIZARDS, "import/config/flow_config.json")
    flow_cfg["steps"] = {"filename_policy": {"enabled": False}}
    atomic_write_json(fs, RootName.WIZARDS, "import/config/flow_config.json", flow_cfg)
    snapshot_after = read_json(fs, RootName.WIZARDS, f"{session_dir}/effective_model.json")

    assert snapshot_after == snapshot_before
