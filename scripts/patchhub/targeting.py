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


def derive_target_options(runner_config_toml: Path) -> list[str]:
    data = _load_runner_config(Path(runner_config_toml))
    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("runner config [paths] must be a TOML object")
    raw_values = list(paths.get("target_repo_roots", []) or [])
    options: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        token = canonical_target_repo_name_from_root(Path(str(raw)))
        if token in seen:
            continue
        seen.add(token)
        options.append(token)
    return sorted(options)


def validate_targeting_config(
    *,
    runner_config_toml: Path,
    default_target_repo: str,
) -> list[str]:
    options = derive_target_options(runner_config_toml)
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
    )
    return TargetingRuntime(
        default_target_repo=default_target_repo,
        options=options,
        runner_config_toml=runner_cfg_path,
    )
