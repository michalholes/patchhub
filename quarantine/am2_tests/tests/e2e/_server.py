from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


def _bootstrap_paths() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    repo_root_str = str(repo_root)
    src_root_str = str(repo_root / "src")
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    return repo_root


def main() -> None:
    repo_root = _bootstrap_paths()

    from plugins.web_interface.core import WebInterfacePlugin

    from audiomason.core.loader import PluginLoader

    host = os.getenv("E2E_HOST", "127.0.0.1")
    port = int(os.getenv("E2E_PORT", "8081"))
    verbosity = int(os.getenv("E2E_WEB_VERBOSITY", "0"))

    loader = PluginLoader(builtin_plugins_dir=repo_root / "plugins")
    app = WebInterfacePlugin().create_app(plugin_loader=loader, verbosity=verbosity)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="error" if verbosity <= 0 else "info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
