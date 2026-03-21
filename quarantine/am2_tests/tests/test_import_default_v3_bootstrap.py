"""Issue 113: v3 default bootstrap applies across import entry modes."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
canonicalize_wizard_definition = import_module(
    "plugins.import.wizard_definition_model"
).canonicalize_wizard_definition
load_or_bootstrap_wizard_definition = import_module(
    "plugins.import.wizard_definition_model"
).load_or_bootstrap_wizard_definition
build_default_wizard_definition_v3 = import_module(
    "plugins.import.dsl.default_wizard_v3"
).build_default_wizard_definition_v3
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


def _make_engine(
    tmp_path: Path,
    *,
    launcher_mode: str | None = "interactive",
    noninteractive: bool = False,
    nav_ui: str = "prompt",
) -> tuple[ImportWizardEngine, dict[str, Path]]:
    roots = {
        name: tmp_path / name for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    cli_defaults: dict[str, object] = {
        "default_root": "inbox",
        "default_path": "",
        "noninteractive": noninteractive,
        "render": {"nav_ui": nav_ui},
    }
    if launcher_mode is not None:
        cli_defaults["launcher_mode"] = launcher_mode
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
        "plugins": {"import": {"cli": cli_defaults}},
    }
    resolver = ConfigResolver(
        cli_args={},
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver), roots


def _write_source_tree(roots: dict[str, Path]) -> None:
    book_dir = roots["inbox"] / "src" / "Author A" / "Book A"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "track01.mp3").write_text("x", encoding="utf-8")


def test_load_or_bootstrap_can_create_shipped_v3_default(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path)
    fs = engine.get_file_service()

    out = load_or_bootstrap_wizard_definition(fs, bootstrap_default_version=3)
    expected = canonicalize_wizard_definition(build_default_wizard_definition_v3())

    assert out == canonicalize_wizard_definition(out)
    assert out["version"] == 3
    assert out["entry_step_id"] == "select_authors"
    phase1_node = next(
        node for node in out["nodes"] if node["step_id"] == "phase1_runtime_defaults"
    )
    assert phase1_node["op"]["primitive_id"] == "import.phase1_runtime"
    assert any(node["step_id"] == "effective_author" for node in out["nodes"])
    assert any(node["step_id"] == "covers_policy_override_prepare" for node in out["nodes"])
    assert out == expected


def test_load_or_bootstrap_rejects_invalid_authored_artifact_without_overwrite(
    tmp_path: Path,
) -> None:
    engine, _ = _make_engine(tmp_path)
    fs = engine.get_file_service()
    authored = {"version": 3, "entry_step_id": "Bad.Step", "nodes": [], "edges": []}
    atomic_write_json(
        fs,
        RootName.WIZARDS,
        WIZARD_DEFINITION_REL_PATH,
        authored,
    )

    with pytest.raises(Exception) as exc_info:
        load_or_bootstrap_wizard_definition(fs, bootstrap_default_version=3)

    message = str(exc_info.value)
    assert "wizard_definition runtime artifact is invalid" in message
    active = Path(tmp_path / "wizards" / WIZARD_DEFINITION_REL_PATH)
    assert active.exists()
    assert "Bad.Step" in active.read_text(encoding="utf-8")


def test_create_session_bootstraps_v3_for_all_import_entry_modes(
    tmp_path: Path,
) -> None:
    cases = [
        ("missing_launcher_mode", None, False, "prompt"),
        ("launcher_disabled", "disabled", False, "prompt"),
        ("noninteractive", "fixed", True, "prompt"),
        ("inline_nav", "interactive", False, "inline"),
        ("both_nav", "interactive", False, "both"),
    ]

    for label, launcher_mode, noninteractive, nav_ui in cases:
        case_root = tmp_path / label
        case_root.mkdir(parents=True, exist_ok=True)
        engine, roots = _make_engine(
            case_root,
            launcher_mode=launcher_mode,
            noninteractive=noninteractive,
            nav_ui=nav_ui,
        )
        _write_source_tree(roots)

        state = engine.create_session("inbox", "src")

        assert state["session_id"], label
        loaded = engine.get_state(str(state["session_id"]))
        assert loaded["effective_model"]["flowmodel_kind"] == "dsl_step_graph_v3", label
