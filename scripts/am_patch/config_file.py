from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .errors import RunnerError


def default_config_path(scripts_dir: Path) -> Path:
    """Return the default config path (runner-owned, deterministic)."""
    return scripts_dir / "am_patch" / "am_patch.toml"


def resolve_config_path(cli_config: str | None, runner_root: Path, scripts_dir: Path) -> Path:
    """Resolve the runner-owned config path.

    - If cli_config is provided, use it (relative paths are resolved against runner_root).
    - Otherwise use the default config path under scripts/.
    """
    if cli_config:
        path = Path(cli_config)
        return path if path.is_absolute() else (runner_root / path)
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
            for key, value in sec.items():
                if isinstance(key, str):
                    out.setdefault(key, value)

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


def resolve_repo_local_config_path(
    *,
    active_repository_tree_root: Path,
    target_repo_config_relpath: str,
) -> Path:
    relpath = str(target_repo_config_relpath or "").strip()
    if not relpath:
        raise RunnerError("CONFIG", "INVALID", "target_repo_config_relpath must be non-empty")

    rel = Path(relpath)
    if rel.is_absolute():
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "target_repo_config_relpath must be relative to the active repository tree root",
        )

    active_root = active_repository_tree_root.resolve()
    resolved = (active_root / rel).resolve()
    try:
        resolved.relative_to(active_root)
    except ValueError as exc:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "target_repo_config_relpath escapes the active repository tree root",
        ) from exc
    return resolved


def load_repo_local_config(
    *,
    active_repository_tree_root: Path,
    target_repo_config_relpath: str,
) -> tuple[dict[str, Any], bool, Path]:
    path = resolve_repo_local_config_path(
        active_repository_tree_root=active_repository_tree_root,
        target_repo_config_relpath=target_repo_config_relpath,
    )
    cfg, used = load_config(path)
    return cfg, used, path
