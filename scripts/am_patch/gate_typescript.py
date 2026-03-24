from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import RunnerError

if TYPE_CHECKING:
    from .log import Logger


def _norm_typescript_target_prefix(target: str) -> str:
    prefix = str(target).strip().replace("\\", "/")
    if prefix.startswith("./"):
        prefix = prefix[2:]
    for marker in ("*", "?", "["):
        if marker in prefix:
            prefix = prefix.split(marker, 1)[0]
            break
    return prefix.rstrip("/")


def _typescript_target_to_include_glob(target: str) -> str:
    normalized = str(target).strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.rstrip("/")
    if not normalized:
        return ""
    if any(ch in normalized for ch in ("*", "?", "[")):
        return normalized
    return normalized + "/**/*"


def _typescript_targets_to_include(targets: list[str]) -> list[str]:
    includes: list[str] = []
    for target in targets:
        include_glob = _typescript_target_to_include_glob(target)
        if include_glob and include_glob not in includes:
            includes.append(include_glob)
    return includes


def typescript_targets_to_trigger_prefixes(targets: list[str]) -> list[str]:
    prefixes: list[str] = []
    for target in targets:
        prefix = _norm_typescript_target_prefix(target)
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def collect_changed_typescript_root_candidates(
    decision_paths: list[str],
    *,
    targets: list[str],
    extensions: list[str],
) -> list[str]:
    prefixes = typescript_targets_to_trigger_prefixes(targets)
    if not prefixes or not extensions:
        return []

    matched: list[str] = []
    normalized_exts = [ext.lower() for ext in extensions]
    for relpath in decision_paths:
        lower_path = relpath.lower()
        if not any(lower_path.endswith(ext) for ext in normalized_exts):
            continue
        if not any(relpath == prefix or relpath.startswith(prefix + "/") for prefix in prefixes):
            continue
        if relpath not in matched:
            matched.append(relpath)
    matched.sort()
    return matched


def select_existing_typescript_root_files(
    repo_root: Path,
    *,
    decision_paths: list[str],
    targets: list[str],
    extensions: list[str],
) -> list[str]:
    existing: list[str] = []
    for relpath in collect_changed_typescript_root_candidates(
        decision_paths,
        targets=targets,
        extensions=extensions,
    ):
        if (repo_root / relpath).is_file():
            existing.append(relpath)
    return existing


def _tsconfig_relpath_for_generated_file(relpath: str) -> str:
    normalized = relpath.replace("\\", "/")
    if normalized.startswith(("../", "/")):
        return normalized
    return ("../" + normalized.lstrip("./")).replace("\\", "/")


def write_typescript_gate_tsconfig(
    repo_root: Path,
    *,
    base_tsconfig: str,
    include_targets: list[str] | None = None,
    root_files: list[str] | None = None,
) -> Path:
    base_path = repo_root / base_tsconfig
    if not base_path.exists():
        raise RunnerError(
            "CONFIG",
            "TYPESCRIPT_BASE_TSCONFIG_NOT_FOUND",
            f"missing base tsconfig: {base_tsconfig!r}",
        )

    include_targets = list(include_targets or [])
    root_files = list(root_files or [])
    if include_targets and root_files:
        raise RunnerError(
            "CONFIG",
            "INVALID_TYPESCRIPT_GATE_SCOPE",
            "include_targets and root_files are mutually exclusive",
        )

    gen_dir = repo_root / ".am_patch"
    gen_dir.mkdir(parents=True, exist_ok=True)
    gen_path = gen_dir / "tsconfig.typescript_gate.json"
    payload: dict[str, object] = {
        "extends": os.path.relpath(base_path, gen_dir),
    }
    if include_targets:
        payload["include"] = [
            _tsconfig_relpath_for_generated_file(include_glob)
            for include_glob in _typescript_targets_to_include(include_targets)
        ]
    elif root_files:
        payload["files"] = [_tsconfig_relpath_for_generated_file(relpath) for relpath in root_files]
        payload["include"] = []
        payload["include"] = []
    else:
        raise RunnerError(
            "CONFIG",
            "INVALID_TYPESCRIPT_GATE_SCOPE",
            "typescript gate scope must not be empty",
        )
    gen_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return gen_path


def run_typescript_gate(
    logger: Logger,
    cwd: Path,
    *,
    decision_paths: list[str],
    extensions: list[str],
    command: list[str],
    mode: str,
    targets: list[str],
    base_tsconfig: str,
) -> bool:
    cmd0 = [str(item) for item in command if str(item).strip()]
    if not cmd0:
        raise RunnerError(
            "GATES",
            "TYPESCRIPT_CMD",
            "gate_typescript_command must be non-empty",
        )

    base_changed = base_tsconfig.replace("\\", "/").lstrip("./") in decision_paths
    if mode == "always" or base_changed:
        gen_path = write_typescript_gate_tsconfig(
            cwd,
            base_tsconfig=base_tsconfig,
            include_targets=targets,
        )
    else:
        root_candidates = collect_changed_typescript_root_candidates(
            decision_paths,
            targets=targets,
            extensions=extensions,
        )
        if not root_candidates:
            logger.warning_core("gate_typescript=SKIP (no_matching_files)")
            return True
        root_files = select_existing_typescript_root_files(
            cwd,
            decision_paths=decision_paths,
            targets=targets,
            extensions=extensions,
        )
        if not root_files:
            logger.warning_core("gate_typescript=SKIP (no_existing_root_files)")
            return True
        gen_path = write_typescript_gate_tsconfig(
            cwd,
            base_tsconfig=base_tsconfig,
            root_files=root_files,
        )

    argv = [*cmd0, "--project", str(gen_path)]
    result = logger.run_logged(argv, cwd=cwd)
    return result.returncode == 0
