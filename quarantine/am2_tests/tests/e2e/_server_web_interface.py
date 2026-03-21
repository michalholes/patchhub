from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import uvicorn


def _bootstrap_paths() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    path_items = [repo_root, repo_root / "src"]
    for item in path_items:
        item_str = str(item)
        if item_str not in sys.path:
            sys.path.insert(0, item_str)
    return repo_root


def _build_defaults(state_dir: Path) -> dict[str, object]:
    roots = {
        name: state_dir / name for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)

    return {
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
                    "default_path": ".",
                    "noninteractive": False,
                    "render": {"nav_ui": "prompt"},
                }
            }
        },
    }


def _seed_inbox(state_dir: Path) -> None:
    inbox_root = state_dir / "inbox"
    samples = {
        inbox_root / "Author A" / "Book One" / "track01.mp3": "x",
        inbox_root / "Author A" / "Book Two" / "track02.mp3": "y",
        inbox_root / "Author B" / "Book Three" / "track03.mp3": "z",
    }
    for path, text in samples.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _seed_wizard_definition(state_dir: Path, *, version: int) -> None:
    if version != 3:
        return

    from importlib import import_module

    build_default_v3 = import_module(
        "plugins.import.dsl.default_wizard_v3"
    ).build_default_wizard_definition_v3

    definition = build_default_v3()
    definitions_dir = state_dir / "wizards" / "import" / "definitions"
    definitions_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(definition, ensure_ascii=True, sort_keys=True) + "\n"

    for filename in ("wizard_definition.json", "wizard_definition.draft.json"):
        (definitions_dir / filename).write_text(payload, encoding="utf-8")


def main() -> None:
    repo_root = _bootstrap_paths()

    from importlib import import_module

    from audiomason.core.config import ConfigResolver
    from audiomason.core.loader import PluginLoader
    from plugins.web_interface.core import WebInterfacePlugin

    import_plugin_cls = import_module("plugins.import.plugin").ImportPlugin

    host = os.getenv("E2E_HOST", "127.0.0.1")
    port = int(os.getenv("E2E_PORT", "8081"))
    verbosity = int(os.getenv("E2E_WEB_VERBOSITY", "0"))
    state_dir = Path(os.environ["E2E_STATE_DIR"]).resolve()

    _seed_inbox(state_dir)
    _seed_wizard_definition(
        state_dir,
        version=int(os.getenv("E2E_IMPORT_WD_VERSION", "2")),
    )
    defaults = _build_defaults(state_dir)
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=state_dir / "no_user_config.yaml",
        system_config_path=state_dir / "no_system_config.yaml",
    )

    loader = PluginLoader(builtin_plugins_dir=repo_root / "plugins")
    loader._plugins["import"] = import_plugin_cls(resolver=resolver)

    app = WebInterfacePlugin().create_app(
        config_resolver=resolver,
        plugin_loader=loader,
        verbosity=verbosity,
    )

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="error" if verbosity <= 0 else "info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
