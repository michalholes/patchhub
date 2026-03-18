from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from am_patch.errors import RunnerError


@dataclass(frozen=True)
class RootModel:
    runner_root: Path
    artifacts_root: Path
    active_target_repo_root: Path
    effective_target_repo_name: str
    target_repo_roots: tuple[Path, ...]
    patch_root: Path


def _resolve_runner_relative(raw: str | None, *, runner_root: Path) -> Path | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    path = Path(text)
    base = path if path.is_absolute() else (runner_root / path)
    return base.resolve()


def _resolved_registry(raw_values: list[str], *, runner_root: Path) -> tuple[Path, ...]:
    out: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_values:
        resolved = _resolve_runner_relative(raw, runner_root=runner_root)
        if resolved is None or resolved in seen:
            continue
        out.append(resolved)
        seen.add(resolved)
    return tuple(out)


def _resolve_artifacts_root(policy: object, *, runner_root: Path) -> Path:
    artifacts_root = _resolve_runner_relative(
        getattr(policy, "artifacts_root", None), runner_root=runner_root
    )
    return runner_root if artifacts_root is None else artifacts_root


def resolve_patch_root(policy: object, *, runner_root: Path) -> tuple[Path, Path]:
    runner_root = runner_root.resolve()
    artifacts_root = _resolve_artifacts_root(policy, runner_root=runner_root)
    patch_dir = _resolve_runner_relative(
        getattr(policy, "patch_dir", None), runner_root=runner_root
    )
    patch_dir_name = str(getattr(policy, "patch_dir_name", "patches"))
    patch_root = patch_dir if patch_dir is not None else (artifacts_root / patch_dir_name)
    return artifacts_root, patch_root


def _validate_repo_token(value: str, *, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise RunnerError("CONFIG", "INVALID", f"{field} must be non-empty")
    if "\n" in text or "\r" in text:
        raise RunnerError("CONFIG", "INVALID", f"{field} must be a single line")
    if any(ch.isspace() for ch in text):
        raise RunnerError("CONFIG", "INVALID", f"{field} must not contain whitespace")
    if "/" in text or "\\" in text:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"{field} must be a bare token (no path separators): {text!r}",
        )
    try:
        text.encode("ascii")
    except UnicodeEncodeError as e:
        raise RunnerError("CONFIG", "INVALID", f"{field} must be ASCII-only") from e
    return text


def canonical_target_repo_name_from_root(root: Path) -> str:
    resolved = root.resolve()
    parts = resolved.parts
    if len(parts) != 4 or parts[:3] != ("/", "home", "pi"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "selected effective target root must canonically match /home/pi/<name>",
        )
    return _validate_repo_token(parts[3], field="effective_target_repo_name")


def _candidate_target_root(repo_name: str) -> Path:
    return Path("/home/pi") / _validate_repo_token(repo_name, field="target_repo_name")


def _selected_source(policy: object, key: str) -> str:
    src = getattr(policy, "_src", {}) or {}
    return str(src.get(key, "default"))


def _choose_target_root(
    *,
    policy: object,
    runner_root: Path,
    registry: tuple[Path, ...],
    patch_target_repo_name: str | None,
) -> Path:
    active_target = _resolve_runner_relative(
        getattr(policy, "active_target_repo_root", None), runner_root=runner_root
    )
    repo_root_alias = _resolve_runner_relative(
        getattr(policy, "repo_root", None), runner_root=runner_root
    )
    target_repo_name = str(getattr(policy, "target_repo_name", "audiomason2"))
    active_src = _selected_source(policy, "active_target_repo_root")
    repo_src = _selected_source(policy, "repo_root")
    target_src = _selected_source(policy, "target_repo_name")

    if active_target is not None and active_src == "cli":
        return active_target
    if repo_root_alias is not None and repo_src == "cli":
        return repo_root_alias
    if target_src == "cli":
        return _candidate_target_root(target_repo_name)
    if patch_target_repo_name is not None:
        return _candidate_target_root(patch_target_repo_name)
    if active_target is not None:
        return active_target
    if repo_root_alias is not None:
        return repo_root_alias
    if target_src == "config":
        return _candidate_target_root(target_repo_name)
    if not registry:
        return runner_root
    return _candidate_target_root(target_repo_name)


def resolve_root_model(
    policy: object,
    *,
    runner_root: Path,
    patch_target_repo_name: str | None = None,
) -> RootModel:
    runner_root = runner_root.resolve()
    artifacts_root, patch_root = resolve_patch_root(policy, runner_root=runner_root)
    registry = _resolved_registry(
        list(getattr(policy, "target_repo_roots", []) or []), runner_root=runner_root
    )
    active_target = _choose_target_root(
        policy=policy,
        runner_root=runner_root,
        registry=registry,
        patch_target_repo_name=patch_target_repo_name,
    )
    if active_target != runner_root and active_target not in registry:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "active_target_repo_root must resolve to runner_root "
            "or an entry from target_repo_roots",
        )
    return RootModel(
        runner_root=runner_root,
        artifacts_root=artifacts_root,
        active_target_repo_root=active_target,
        effective_target_repo_name=canonical_target_repo_name_from_root(active_target),
        target_repo_roots=registry,
        patch_root=patch_root,
    )
