"""PatchHub entry point.

Contract (HARD):
- Before changing PatchHub behavior, read scripts/patchhub_specification.md.
- Any behavior change (UI/API/validation/defaults) requires:
  - updating scripts/patchhub_specification.md
  - bumping PatchHub runtime version in scripts/patchhub/patchhub.toml ([meta].version)
  - SemVer rules: MAJOR.MINOR.PATCH

Version is NOT hardcoded in code. The source of truth is patchhub.toml.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="patchhub",
        description="PatchHub (AM Patch Web UI)",
    )
    ap.add_argument(
        "--config",
        default="scripts/patchhub/patchhub.toml",
        help="Path to patchhub.toml",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from patchhub.asgi.asgi_server import serve_asgi
    from patchhub.config import load_config

    cfg_path = (repo_root / args.config).resolve()

    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    server_raw = raw.get("server", {})
    backend = str(server_raw.get("backend", "asgi") or "asgi")
    if backend != "asgi":
        print(f"WEB: invalid backend={backend!r}; expected 'asgi'")
        return 2

    cfg = load_config(cfg_path)

    host = cfg.server.host
    port = cfg.server.port
    print(f"ASGI: listening on http://{host}:{port}")
    if host == "0.0.0.0":
        print(f"ASGI: local access http://127.0.0.1:{port}")
    serve_asgi(repo_root=repo_root, cfg=cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
