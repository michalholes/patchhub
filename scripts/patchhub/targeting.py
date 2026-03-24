from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TargetingRuntime:
    default_target_repo: str
    options: list[str]
    runner_config_toml: Path
    resolved_roots_by_token: dict[str, Path]


def validate_target_repo_token(value: str, *, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if "\n" in text or "\r" in text:
        raise ValueError(f"{field} must be a single line")
    if any(ch.isspace() for ch in text):
        raise ValueError(f"{field} must not contain whitespace")
    if "/" in text or "\\" in text:
        raise ValueError(f"{field} must be a bare token (no path separators)")
    try:
        text.encode("ascii")
    except UnicodeEncodeError as e:
        raise ValueError(f"{field} must be ASCII-only") from e
    return text


def canonical_target_repo_name_from_root(root: Path) -> str:
    resolved = Path(root).resolve()
    parts = resolved.parts
    if len(parts) != 4 or parts[:3] != ("/", "home", "pi"):
        raise ValueError("target root must canonically match /home/pi/<name>")
    return validate_target_repo_token(parts[3], field="target_repo_root")


def _load_runner_config(path: Path) -> dict[str, Any]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("runner config must be a TOML object")
    return raw


def _resolve_runner_relative(raw: str | None, *, runner_root: Path) -> Path | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    path = Path(text)
    base = path if path.is_absolute() else (runner_root / path)
    return base.resolve()


def derive_target_repo_roots(
    runner_config_toml: Path,
    *,
    runner_root: Path | None = None,
) -> dict[str, Path]:
    runner_root = (
        Path(runner_root).resolve()
        if runner_root is not None
        else Path(runner_config_toml).resolve().parents[2]
    )
    data = _load_runner_config(Path(runner_config_toml))
    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("runner config [paths] must be a TOML object")
    raw_values = list(paths.get("target_repo_roots", []) or [])
    roots_by_token: dict[str, Path] = {}
    seen_roots: set[Path] = set()
    for raw in raw_values:
        text = str(raw).strip()
        if not text:
            continue
        if "=" in text:
            raw_token, raw_root = text.split("=", 1)
            token = validate_target_repo_token(raw_token, field="target_repo_roots token")
            resolved_root = _resolve_runner_relative(raw_root, runner_root=runner_root)
            if resolved_root is None:
                raise ValueError("target_repo_roots binding root must be non-empty")
        else:
            resolved_root = _resolve_runner_relative(text, runner_root=runner_root)
            if resolved_root is None:
                continue
            token = canonical_target_repo_name_from_root(resolved_root)
        if token in roots_by_token:
            raise ValueError(f"duplicate target_repo_roots token: {token!r}")
        if resolved_root in seen_roots:
            raise ValueError(f"duplicate target_repo_roots root: {resolved_root}")
        roots_by_token[token] = resolved_root
        seen_roots.add(resolved_root)
    return dict(sorted(roots_by_token.items()))


def derive_target_options(
    runner_config_toml: Path,
    *,
    runner_root: Path | None = None,
) -> list[str]:
    return list(
        derive_target_repo_roots(
            runner_config_toml,
            runner_root=runner_root,
        ).keys()
    )


def validate_targeting_config(
    *,
    runner_config_toml: Path,
    default_target_repo: str,
    runner_root: Path | None = None,
) -> list[str]:
    options = derive_target_options(
        runner_config_toml,
        runner_root=runner_root,
    )
    default_token = validate_target_repo_token(
        default_target_repo,
        field="default_target_repo",
    )
    if default_token not in options:
        raise ValueError("default_target_repo must be present in target_repo_roots")
    return options


def validate_selected_target_repo(target_repo: str, options: list[str]) -> str:
    token = validate_target_repo_token(target_repo, field="target_repo")
    if token not in options:
        raise ValueError("target_repo must be one of targeting.options")
    return token


def targeting_default_target_repo(target_cfg: Any) -> str:
    value = str(getattr(target_cfg, "default_target_repo", "patchhub") or "").strip()
    return validate_target_repo_token(value or "patchhub", field="default_target_repo")


def resolve_targeting_runtime(
    *,
    repo_root: Path,
    runner_config_toml: str,
    target_cfg: Any,
) -> TargetingRuntime:
    default_target_repo = targeting_default_target_repo(target_cfg)
    runner_rel = str(runner_config_toml or "").strip()
    if not runner_rel:
        raise ValueError("runner.runner_config_toml must be configured")
    runner_cfg_path = (Path(repo_root) / runner_rel).resolve()
    options = validate_targeting_config(
        runner_config_toml=runner_cfg_path,
        default_target_repo=default_target_repo,
        runner_root=repo_root,
    )
    resolved_roots_by_token = derive_target_repo_roots(
        runner_cfg_path,
        runner_root=repo_root,
    )
    return TargetingRuntime(
        default_target_repo=default_target_repo,
        options=options,
        runner_config_toml=runner_cfg_path,
        resolved_roots_by_token=resolved_roots_by_token,
    )
