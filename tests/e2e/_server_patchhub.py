from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

import uvicorn


class _ConfigWithPaths(Protocol):
    paths: object


def _bootstrap_paths() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    path_items = [repo_root, repo_root / "src", repo_root / "scripts"]
    for item in path_items:
        item_str = str(item)
        if item_str not in sys.path:
            sys.path.insert(0, item_str)
    return repo_root


def _with_e2e_patches_root(cfg: object) -> object:
    raw = os.getenv("E2E_PATCHES_ROOT", "").strip()
    if not raw:
        return cfg
    patches_root = Path(raw).resolve()
    patches_root.mkdir(parents=True, exist_ok=True)
    upload_dir = str((patches_root / "incoming").resolve())
    replace_obj = cast(Callable[..., object], replace)
    cfg_paths = cast(_ConfigWithPaths, cfg).paths
    return replace_obj(
        cfg,
        paths=replace_obj(
            cfg_paths,
            patches_root=str(patches_root),
            upload_dir=upload_dir,
        ),
    )


def main() -> None:
    repo_root = _bootstrap_paths()

    from patchhub.asgi.asgi_app import create_app
    from patchhub.config import load_config

    host = os.getenv("E2E_HOST", "127.0.0.1")
    port = int(os.getenv("E2E_PORT", "8091"))

    cfg = load_config(repo_root / "scripts" / "patchhub" / "patchhub.toml")
    cfg = _with_e2e_patches_root(cfg)
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
