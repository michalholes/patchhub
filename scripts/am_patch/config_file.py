from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def default_config_path(scripts_dir: Path) -> Path:
    """Return the default config path (runner-owned, deterministic)."""
    return scripts_dir / "am_patch" / "am_patch.toml"


def resolve_config_path(cli_config: str | None, runner_root: Path, scripts_dir: Path) -> Path:
    """Resolve the runner-owned config path.

    - If cli_config is provided, use it (relative paths are resolved against runner_root).
    - Otherwise use the default config path under scripts/.
    """
    if cli_config:
        p = Path(cli_config)
        return p if p.is_absolute() else (runner_root / p)
    return default_config_path(scripts_dir)


def _flatten_sections(cfg: dict[str, object]) -> dict[str, object]:
    if not isinstance(cfg, dict):
        return {}
    out: dict[str, object] = dict(cfg)
    for section in (
        "git",
        "paths",
        "workspace",
        "patch",
        "scope",
        "gates",
        "promotion",
        "security",
        "logging",
        "audit",
    ):
        sec = cfg.get(section)
        if isinstance(sec, dict):
            for k, v in sec.items():
                if isinstance(k, str):
                    out.setdefault(k, v)

    if "order" in out and "gates_order" not in out:
        out["gates_order"] = out["order"]
    if "enforce_files_only" in out and "enforce_allowed_files" not in out:
        out["enforce_allowed_files"] = out["enforce_files_only"]
    if "rollback_on_failure" in out and "no_rollback" not in out:
        out["no_rollback"] = not bool(out["rollback_on_failure"])
    if "delete_on_success" in out and "delete_workspace_on_success" not in out:
        out["delete_workspace_on_success"] = out["delete_on_success"]
    return out


def load_config(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {}, False
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return _flatten_sections(data), True
