from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from am_patch.errors import RunnerError


@dataclass(frozen=True)
class TargetBinding:
    token: str
    root: Path


@dataclass(frozen=True)
class RootModel:
    runner_root: Path
    artifacts_root: Path
    live_target_root: Path
    active_repository_tree_root: Path
    effective_target_repo_name: str
    target_repo_roots: tuple[Path, ...]
    patch_root: Path

    @property
    def active_target_repo_root(self) -> Path:
        return self.live_target_root


def _resolve_runner_relative(raw: str | None, *, runner_root: Path) -> Path | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    path = Path(text)
    base = path if path.is_absolute() else (runner_root / path)
    return base.resolve()


def _resolve_artifacts_root(policy: object, *, runner_root: Path) -> Path:
    artifacts_root = _resolve_runner_relative(
        getattr(policy, "artifacts_root", None),
        runner_root=runner_root,
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
    except UnicodeEncodeError as exc:
        raise RunnerError("CONFIG", "INVALID", f"{field} must be ASCII-only") from exc
    return text


def _validated_basename(root: Path, *, field: str) -> str:
    return _validate_repo_token(root.resolve().name, field=field)


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


def _selected_source(policy: object, key: str) -> str:
    src = getattr(policy, "_src", {}) or {}
    return str(src.get(key, "default"))


def _legacy_binding_token(root: Path) -> str:
    try:
        return canonical_target_repo_name_from_root(root)
    except RunnerError as exc:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "legacy target_repo_roots entries must canonically match /home/pi/<name>",
        ) from exc


def resolve_target_bindings(
    raw_values: list[str],
    *,
    runner_root: Path,
) -> tuple[TargetBinding, ...]:
    bindings: list[TargetBinding] = []
    seen_tokens: set[str] = set()
    seen_roots: set[Path] = set()
    for raw in raw_values:
        text = str(raw).strip()
        if not text:
            continue
        if "=" in text:
            raw_token, raw_root = text.split("=", 1)
            token = _validate_repo_token(raw_token, field="target_repo_roots token")
            resolved_root = _resolve_runner_relative(raw_root, runner_root=runner_root)
            if resolved_root is None:
                raise RunnerError(
                    "CONFIG",
                    "INVALID",
                    "target_repo_roots binding root must be non-empty",
                )
        else:
            resolved_root = _resolve_runner_relative(text, runner_root=runner_root)
            if resolved_root is None:
                continue
            token = _legacy_binding_token(resolved_root)
        if token in seen_tokens:
            raise RunnerError(
                "CONFIG",
                "INVALID",
                f"duplicate target_repo_roots token: {token!r}",
            )
        if resolved_root in seen_roots:
            raise RunnerError(
                "CONFIG",
                "INVALID",
                f"duplicate target_repo_roots root: {resolved_root}",
            )
        bindings.append(TargetBinding(token=token, root=resolved_root))
        seen_tokens.add(token)
        seen_roots.add(resolved_root)
    return tuple(bindings)


def target_binding_for_token(
    bindings: tuple[TargetBinding, ...],
    token: str,
    *,
    field: str,
) -> TargetBinding:
    wanted = _validate_repo_token(token, field=field)
    for binding in bindings:
        if binding.token == wanted:
            return binding
    raise RunnerError(
        "CONFIG",
        "INVALID",
        f"{field} must resolve via target_repo_roots binding registry: {wanted!r}",
    )


def target_binding_for_root(
    bindings: tuple[TargetBinding, ...],
    root: Path,
    *,
    field: str,
) -> TargetBinding:
    resolved = root.resolve()
    for binding in bindings:
        if binding.root == resolved:
            return binding
    raise RunnerError(
        "CONFIG",
        "INVALID",
        f"{field} must resolve to an entry from target_repo_roots",
    )


def _zero_config_binding(runner_root: Path) -> TargetBinding:
    return TargetBinding(
        token=_validated_basename(runner_root, field="effective_target_repo_name"),
        root=runner_root.resolve(),
    )


def _zero_config_binding_for_selector(
    *,
    runner_root: Path,
    field: str,
    token: str | None = None,
    root: Path | None = None,
) -> TargetBinding:
    binding = _zero_config_binding(runner_root)
    if token is not None and _validate_repo_token(token, field=field) != binding.token:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"{field} must match the zero-config runner_root basename: {binding.token!r}",
        )
    if root is not None and root.resolve() != binding.root:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"{field} must resolve to runner_root in zero-config single-repo mode",
        )
    return binding


def _choose_target_binding(
    *,
    policy: object,
    runner_root: Path,
    bindings: tuple[TargetBinding, ...],
    patch_target_repo_name: str | None,
    workspace_target_repo_name: str | None,
) -> TargetBinding:
    active_target = _resolve_runner_relative(
        getattr(policy, "active_target_repo_root", None),
        runner_root=runner_root,
    )
    repo_root_alias = _resolve_runner_relative(
        getattr(policy, "repo_root", None), runner_root=runner_root
    )
    target_repo_name = str(getattr(policy, "target_repo_name", "") or "").strip()
    active_src = _selected_source(policy, "active_target_repo_root")
    repo_src = _selected_source(policy, "repo_root")
    target_src = _selected_source(policy, "target_repo_name")

    if not bindings:
        if workspace_target_repo_name is not None:
            return _zero_config_binding_for_selector(
                runner_root=runner_root,
                field="workspace target_repo_name",
                token=workspace_target_repo_name,
            )
        if active_target is not None and active_src == "cli":
            return _zero_config_binding_for_selector(
                runner_root=runner_root,
                field="active_target_repo_root",
                root=active_target,
            )
        if repo_root_alias is not None and repo_src == "cli":
            return _zero_config_binding_for_selector(
                runner_root=runner_root,
                field="repo_root",
                root=repo_root_alias,
            )
        if target_src == "cli" and target_repo_name:
            return _zero_config_binding_for_selector(
                runner_root=runner_root,
                field="target_repo_name",
                token=target_repo_name,
            )
        if patch_target_repo_name is not None:
            return _zero_config_binding_for_selector(
                runner_root=runner_root,
                field="patch target_repo_name",
                token=patch_target_repo_name,
            )
        if active_target is not None:
            return _zero_config_binding_for_selector(
                runner_root=runner_root,
                field="active_target_repo_root",
                root=active_target,
            )
        if repo_root_alias is not None:
            return _zero_config_binding_for_selector(
                runner_root=runner_root,
                field="repo_root",
                root=repo_root_alias,
            )
        if target_repo_name:
            return _zero_config_binding_for_selector(
                runner_root=runner_root,
                field="target_repo_name",
                token=target_repo_name,
            )
        return _zero_config_binding(runner_root)

    if workspace_target_repo_name is not None:
        return target_binding_for_token(
            bindings,
            workspace_target_repo_name,
            field="workspace target_repo_name",
        )
    if active_target is not None and active_src == "cli":
        return target_binding_for_root(bindings, active_target, field="active_target_repo_root")
    if repo_root_alias is not None and repo_src == "cli":
        return target_binding_for_root(bindings, repo_root_alias, field="repo_root")
    if target_src == "cli" and target_repo_name:
        return target_binding_for_token(bindings, target_repo_name, field="target_repo_name")
    if patch_target_repo_name is not None:
        return target_binding_for_token(
            bindings,
            patch_target_repo_name,
            field="patch target_repo_name",
        )
    if active_target is not None:
        return target_binding_for_root(bindings, active_target, field="active_target_repo_root")
    if repo_root_alias is not None:
        return target_binding_for_root(bindings, repo_root_alias, field="repo_root")
    if target_repo_name:
        return target_binding_for_token(bindings, target_repo_name, field="target_repo_name")

    if len(bindings) == 1:
        return bindings[0]

    runner_matches = [binding for binding in bindings if binding.root == runner_root.resolve()]
    if len(runner_matches) == 1:
        return runner_matches[0]
    if len(runner_matches) > 1:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "runner_root matches multiple target_repo_roots entries",
        )
    return bindings[0]


def resolve_root_model(
    policy: object,
    *,
    runner_root: Path,
    patch_target_repo_name: str | None = None,
    workspace_target_repo_name: str | None = None,
    active_repository_tree_root: Path | None = None,
) -> RootModel:
    runner_root = runner_root.resolve()
    artifacts_root, patch_root = resolve_patch_root(policy, runner_root=runner_root)
    bindings = resolve_target_bindings(
        list(getattr(policy, "target_repo_roots", []) or []),
        runner_root=runner_root,
    )
    selected = _choose_target_binding(
        policy=policy,
        runner_root=runner_root,
        bindings=bindings,
        patch_target_repo_name=patch_target_repo_name,
        workspace_target_repo_name=workspace_target_repo_name,
    )
    active_root = (
        active_repository_tree_root.resolve() if active_repository_tree_root else selected.root
    )
    return RootModel(
        runner_root=runner_root,
        artifacts_root=artifacts_root,
        live_target_root=selected.root,
        active_repository_tree_root=active_root,
        effective_target_repo_name=selected.token,
        target_repo_roots=tuple(binding.root for binding in bindings),
        patch_root=patch_root,
    )
