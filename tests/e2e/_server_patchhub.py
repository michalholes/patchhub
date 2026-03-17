from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


def _bootstrap_paths() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    path_items = [repo_root, repo_root / "src", repo_root / "scripts"]
    for item in path_items:
        item_str = str(item)
        if item_str not in sys.path:
            sys.path.insert(0, item_str)
    return repo_root


def main() -> None:
    repo_root = _bootstrap_paths()

    from patchhub.asgi.asgi_app import create_app
    from patchhub.config import load_config

    host = os.getenv("E2E_HOST", "127.0.0.1")
    port = int(os.getenv("E2E_PORT", "8091"))

    cfg = load_config(repo_root / "scripts" / "patchhub" / "patchhub.toml")
    app = create_app(repo_root=repo_root, cfg=cfg)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="error",
        access_log=False,
    )


if __name__ == "__main__":
    main()
