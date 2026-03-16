from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from am_patch.errors import RunnerError


@dataclass(frozen=True)
class RootModel:
    runner_root: Path
    artifacts_root: Path
    active_target_repo_root: Path
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


def resolve_root_model(policy: object, *, runner_root: Path) -> RootModel:
    runner_root = runner_root.resolve()
    artifacts_root = _resolve_runner_relative(
        getattr(policy, "artifacts_root", None), runner_root=runner_root
    )
    if artifacts_root is None:
        artifacts_root = runner_root

    registry = _resolved_registry(
        list(getattr(policy, "target_repo_roots", []) or []), runner_root=runner_root
    )
    active_target = _resolve_runner_relative(
        getattr(policy, "active_target_repo_root", None), runner_root=runner_root
    )
    active_target_source = "active_target_repo_root" if active_target is not None else None
    if active_target is None:
        active_target = _resolve_runner_relative(
            getattr(policy, "repo_root", None), runner_root=runner_root
        )
        if active_target is not None:
            active_target_source = "repo_root"
    if active_target is None:
        active_target = runner_root

    enforce_registry = active_target_source in {"active_target_repo_root", "repo_root"}
    if enforce_registry and active_target != runner_root and active_target not in registry:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"{active_target_source} must resolve to runner_root "
            "or an entry from target_repo_roots",
        )

    patch_dir = _resolve_runner_relative(
        getattr(policy, "patch_dir", None), runner_root=runner_root
    )
    patch_dir_name = str(getattr(policy, "patch_dir_name", "patches"))
    patch_root = patch_dir if patch_dir is not None else (artifacts_root / patch_dir_name)

    return RootModel(
        runner_root=runner_root,
        artifacts_root=artifacts_root,
        active_target_repo_root=active_target,
        target_repo_roots=registry,
        patch_root=patch_root,
    )
