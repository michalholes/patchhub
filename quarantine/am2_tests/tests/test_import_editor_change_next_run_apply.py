"""Issue 112: editor changes apply to the next v3 import session only."""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
wizard_storage = import_module("plugins.import.wizard_editor_storage")
read_json = import_module("plugins.import.storage").read_json
RootName = import_module("plugins.file_io.service.types").RootName


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, dict[str, Path]]:
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
                    "default_path": "",
                    "noninteractive": False,
                    "render": {"nav_ui": "prompt"},
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


def _write_source_tree(roots: dict[str, Path]) -> None:
    book_dir = roots["inbox"] / "src" / "Author A" / "Book A"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "track01.mp3").write_text("x", encoding="utf-8")


def _workflow_node(workflow: dict[str, object], step_id: str) -> dict[str, object]:
    nodes = workflow.get("nodes")
    assert isinstance(nodes, list)
    for node in nodes:
        if isinstance(node, dict) and node.get("step_id") == step_id:
            return node
    raise AssertionError(f"missing workflow step: {step_id}")


def test_v3_editor_activation_affects_only_the_next_import_run(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_source_tree(roots)

    state1 = engine.create_session("inbox", "src")
    session_id_1 = str(state1["session_id"])
    engine.submit_step(session_id_1, "select_authors", {"selection": "all"})

    step1 = engine.get_step_definition(session_id_1, "select_books")
    assert step1["ui"]["label"] == "Books"

    fs = engine.get_file_service()
    draft = deepcopy(wizard_storage.get_wizard_definition_draft(fs))
    assert draft["version"] == 3

    for node in draft["nodes"]:
        if node.get("step_id") != "select_books":
            continue
        node["op"] = dict(node.get("op") or {})
        inputs = dict(node["op"].get("inputs") or {})
        inputs["label"] = "Edited Books"
        node["op"]["inputs"] = inputs

    wizard_storage.put_wizard_definition_draft(fs, draft)
    wizard_storage.activate_wizard_definition_draft(fs)

    state2 = engine.create_session("inbox", "src")
    session_id_2 = str(state2["session_id"])
    assert session_id_2 != session_id_1

    workflow1 = read_json(
        fs,
        RootName.WIZARDS,
        f"import/sessions/{session_id_1}/effective_workflow.json",
    )
    workflow2 = read_json(
        fs,
        RootName.WIZARDS,
        f"import/sessions/{session_id_2}/effective_workflow.json",
    )
    assert _workflow_node(workflow1, "select_books")["op"]["inputs"]["label"] == "Books"
    assert _workflow_node(workflow2, "select_books")["op"]["inputs"]["label"] == "Edited Books"

    engine.submit_step(session_id_2, "select_authors", {"selection": "all"})
    step2 = engine.get_step_definition(session_id_2, "select_books")
    assert step2["ui"]["label"] == "Edited Books"

    step1_again = engine.get_step_definition(session_id_1, "select_books")
    assert step1_again["ui"]["label"] == "Books"
