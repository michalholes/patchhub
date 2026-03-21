"""Issue 109: CLI/Web parity for v3 prompt metadata and autofill path."""

from __future__ import annotations

import json
import subprocess
from importlib import import_module
from pathlib import Path
from typing import Any

from audiomason.core.config import ConfigResolver

cli_renderer = import_module("plugins.import.cli_renderer")
run_launcher = cli_renderer.run_launcher
ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH


PARITY_FLOW = {
    "version": 3,
    "entry_step_id": "ask_name",
    "nodes": [
        {
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {
                    "label": "Display name",
                    "prompt": "Enter the final display name",
                    "help": "CLI and Web must render the same metadata",
                    "hint": "Press Enter to accept the backend prefill",
                    "examples": ["Ada", "Grace"],
                    "prefill": "Ada",
                },
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
    "edges": [{"from": "ask_name", "to": "stop"}],
}

AUTOFILL_FLOW = {
    "version": 3,
    "entry_step_id": "seed_name",
    "nodes": [
        {
            "step_id": "seed_name",
            "op": {
                "primitive_id": "data.set",
                "primitive_version": 1,
                "inputs": {"value": "Ada"},
                "writes": [
                    {
                        "to_path": "$.state.vars.autofill_name",
                        "value": {"expr": "$.op.outputs.value"},
                    }
                ],
            },
        },
        {
            "step_id": "seed_flag",
            "op": {
                "primitive_id": "data.set",
                "primitive_version": 1,
                "inputs": {"value": True},
                "writes": [
                    {
                        "to_path": "$.state.vars.should_autofill",
                        "value": {"expr": "$.op.outputs.value"},
                    }
                ],
            },
        },
        {
            "step_id": "ask_name",
            "op": {
                "primitive_id": "ui.prompt_text",
                "primitive_version": 1,
                "inputs": {
                    "prompt": "Enter the final display name",
                    "default_expr": {"expr": "$.state.vars.autofill_name"},
                    "autofill_if": {"expr": "$.state.vars.should_autofill"},
                },
                "writes": [
                    {
                        "to_path": "$.state.answers.ask_name.value",
                        "value": {"expr": "$.op.outputs.value"},
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
    "edges": [
        {"from": "seed_name", "to": "seed_flag"},
        {"from": "seed_flag", "to": "ask_name"},
        {"from": "ask_name", "to": "stop"},
    ],
}


def _make_engine(tmp_path: Path) -> tuple[Any, ConfigResolver]:
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
                    "render": {"confirm_defaults": True},
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
    return ImportWizardEngine(resolver=resolver), resolver


def _run_v3_renderer(function_name: str, payload: dict[str, Any]) -> Any:
    script = """
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("plugins/import/ui/web/assets/import_wizard_v3.js", "utf8");
const sandbox = { window: {}, globalThis: {}, console };
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "import_wizard_v3.js" });
const api = sandbox.window.AM2ImportWizardV3 || sandbox.globalThis.AM2ImportWizardV3;
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const out = api[payload.function_name](payload.argument);
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"function_name": function_name, "argument": payload}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_cli_and_web_share_same_prompt_metadata_projection(tmp_path: Path) -> None:
    engine, resolver = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, PARITY_FLOW)

    state = engine.create_session("inbox", "")
    step = engine.get_step_definition(state["session_id"], "ask_name")
    model = _run_v3_renderer("buildPromptModel", step)

    printed: list[str] = []
    responses = iter(["1", ""])
    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=lambda _prompt: next(responses),
        print_fn=printed.append,
    )

    assert rc == 0
    joined = "\n".join(printed)
    assert f"Label: {model['label']}" in joined
    assert f"Prompt: {model['prompt']}" in joined
    assert f"Help: {model['help']}" in joined
    assert f"Hint: {model['hint']}" in joined
    assert f"Prefill: {model['prefill']}" in joined


def test_autofill_path_is_backend_driven_for_cli_and_web(tmp_path: Path) -> None:
    engine, resolver = _make_engine(tmp_path)
    fs = engine.get_file_service()
    atomic_write_json(fs, RootName.WIZARDS, WIZARD_DEFINITION_REL_PATH, AUTOFILL_FLOW)

    state = engine.create_session("inbox", "")
    assert state["status"] == "completed"
    assert state["current_step_id"] == "stop"

    can_render = _run_v3_renderer("canRenderCurrentStep", state)
    assert can_render is False

    printed: list[str] = []

    responses = iter(["1"])

    rc = run_launcher(
        engine=engine,
        resolver=resolver,
        cli_overrides={},
        input_fn=lambda _prompt: next(responses),
        print_fn=printed.append,
    )

    assert rc == 0
    joined = "\n".join(printed)
    assert '"status": "completed"' in joined
    assert "Prompt: Enter the final display name" not in joined


def _write_selection_tree(tmp_path: Path) -> None:
    for rel_path in ("A/Book1/a.txt", "B/Book2/b.txt"):
        path = tmp_path / "inbox" / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


def test_cli_and_web_share_same_prompt_select_display_items(tmp_path: Path) -> None:
    engine, _resolver = _make_engine(tmp_path)
    _write_selection_tree(tmp_path)

    state = engine.create_session("inbox", "")
    step = engine.get_step_definition(state["session_id"], "select_authors")
    metadata = cli_renderer._v3_prompt_metadata(step)
    assert isinstance(metadata, dict)

    model = _run_v3_renderer("buildPromptModel", step)
    assert model["items"] == [
        {
            "item_id": step["ui"]["items"][0]["item_id"],
            "label": "A",
        },
        {
            "item_id": step["ui"]["items"][1]["item_id"],
            "label": "B",
        },
    ]

    printed: list[str] = []
    payload, rc = cli_renderer._collect_v3_prompt_payload(
        engine=engine,
        session_id=str(state["session_id"]),
        step=step,
        metadata=metadata,
        input_fn=lambda _prompt: "",
        print_fn=printed.append,
        confirm_defaults=True,
        allow_inline=False,
    )

    assert rc is None
    assert payload == {"selection": "all"}
    joined = "\n".join(printed)
    assert "Options:" in joined
    assert "  1. A" in joined
    assert "  2. B" in joined


def test_cli_and_web_share_scoped_author_prompt_select_display_items(
    tmp_path: Path,
) -> None:
    engine, _resolver = _make_engine(tmp_path)
    for rel_path in ("A/Book1/a.txt", "A/Book2/b.txt"):
        path = tmp_path / "inbox" / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    state = engine.create_session("inbox", "A")
    assert state["current_step_id"] == "select_books"
    step = engine.get_step_definition(state["session_id"], "select_books")
    metadata = cli_renderer._v3_prompt_metadata(step)
    assert isinstance(metadata, dict)

    model = _run_v3_renderer("buildPromptModel", step)
    assert model["items"] == [
        {
            "item_id": step["ui"]["items"][0]["item_id"],
            "label": "A / Book1",
        },
        {
            "item_id": step["ui"]["items"][1]["item_id"],
            "label": "A / Book2",
        },
    ]

    printed: list[str] = []
    payload, rc = cli_renderer._collect_v3_prompt_payload(
        engine=engine,
        session_id=str(state["session_id"]),
        step=step,
        metadata=metadata,
        input_fn=lambda _prompt: "",
        print_fn=printed.append,
        confirm_defaults=True,
        allow_inline=False,
    )

    assert rc is None
    assert payload == {"selection": "all"}
    joined = "\n".join(printed)
    assert "Options:" in joined
    assert "  1. A / Book1" in joined
    assert "  2. A / Book2" in joined


def test_web_start_processing_posts_canonical_confirm_payload() -> None:
    js = Path("plugins/import/ui/web/assets/import_wizard.js").read_text(encoding="utf-8")
    assert "body: JSON.stringify({ confirm: true })" in js
    assert 'body: "{}"' not in js
