from __future__ import annotations

from pathlib import Path

import uvicorn

from patchhub.config import AppConfig

from .asgi_app import create_app


def serve_asgi(*, repo_root: Path, cfg: AppConfig) -> None:
    app = create_app(repo_root=repo_root, cfg=cfg)

    uvicorn.run(
        app,
        host=str(cfg.server.host),
        port=int(cfg.server.port),
        log_level="info",
    )
