from __future__ import annotations

import os
import shutil
import site
import sys
import tomllib
from pathlib import Path
from typing import Any, NamedTuple

from .errors import RunnerError
from .scope import changed_path_entries


class _BindTarget(NamedTuple):
    path: Path
    is_dir: bool


class _RuntimeContext(NamedTuple):
    workspaces_dir: Path
    cli_mode: str
    issue_id: str | None


_RUNTIME_CONTEXT: _RuntimeContext | None = None
_FALLBACK_GIT_USER_NAME = "BadGuys Suite Jail"
_FALLBACK_GIT_USER_EMAIL = "badguys-suite-jail@example.invalid"
_BWRAP_ERROR = "FAIL: bwrap not found (install bubblewrap or use --no-suite-jail)"


def configure_badguys_runtime(*, workspaces_dir: Path, cli_mode: str, issue_id: str | None) -> None:
    global _RUNTIME_CONTEXT
    _RUNTIME_CONTEXT = _RuntimeContext(
        Path(workspaces_dir),
        str(cli_mode),
        None if issue_id is None else str(issue_id),
    )


def run_badguys_gate(
    logger: Any,
    cwd: Path,
    *,
    repo_root: Path,
    decision_paths: list[str],
    skip_badguys: bool,
    gate_badguys_mode: str,
    gate_badguys_trigger_prefixes: list[str],
    gate_badguys_trigger_files: list[str],
    gate_badguys_command: list[str],
) -> bool:
    del repo_root
    if skip_badguys:
        logger.warning_core("gate_badguys=SKIP (skipped_by_user)")
        return True

    mode = str(gate_badguys_mode).strip().lower()
    if mode not in {"auto", "always"}:
        raise RunnerError(
            "CONFIG",
            "INVALID_BADGUYS_MODE",
            f"invalid gate_badguys_mode: {gate_badguys_mode!r}",
        )
    if mode == "auto" and not _trigger_matches(
        decision_paths,
        prefixes=gate_badguys_trigger_prefixes,
        files=gate_badguys_trigger_files,
    ):
        logger.warning_core("gate_badguys=SKIP (no_matching_files)")
        return True

    runtime = _require_runtime_context()
    source_repo_root = Path(cwd)
    jail_root = runtime.workspaces_dir / "_badguys_gate" / _runtime_tag(runtime)
    jail_repo_root = jail_root / "repo"
    bind_targets = _resolve_bind_targets(
        source_repo_root=source_repo_root,
        run_id=_runtime_tag(runtime),
    )
    external_bind_paths = _external_bind_paths(repo_root=source_repo_root)
    command = _ensure_no_suite_jail(gate_badguys_command)
    env = _build_jail_env(source_repo_root=source_repo_root, run_id=_runtime_tag(runtime))

    if jail_root.exists():
        shutil.rmtree(jail_root, ignore_errors=True)
    jail_root.parent.mkdir(parents=True, exist_ok=True)
    jail_root.mkdir(parents=True, exist_ok=True)
    logger.line(f"gate_badguys_repo=JAIL {source_repo_root} -> {jail_repo_root}")

    try:
        _bootstrap_jail_repo(
            logger,
            source_repo_root=source_repo_root,
            jail_repo_root=jail_repo_root,
        )
        _prepare_bind_targets(
            source_repo_root=source_repo_root,
            jail_repo_root=jail_repo_root,
            bind_targets=bind_targets,
        )
        _materialize_changed_paths(
            logger,
            source_repo_root=source_repo_root,
            jail_repo_root=jail_repo_root,
            bind_targets=bind_targets,
        )
        return _run_badguys_in_jail(
            logger,
            source_repo_root=source_repo_root,
            jail_repo_root=jail_repo_root,
            bind_targets=bind_targets,
            external_bind_paths=external_bind_paths,
            command=command,
            env=env,
        )
    finally:
        shutil.rmtree(jail_root, ignore_errors=True)


def _require_runtime_context() -> _RuntimeContext:
    if _RUNTIME_CONTEXT is None:
        raise RunnerError("CONFIG", "INVALID", "badguys runtime context missing")
    return _RUNTIME_CONTEXT


def _runtime_tag(runtime: _RuntimeContext) -> str:
    return f"{runtime.cli_mode}_{runtime.issue_id or 'noissue'}"


def _trigger_matches(decision_paths: list[str], *, prefixes: list[str], files: list[str]) -> bool:
    normalized = [_normalize_path(path) for path in decision_paths]
    for path in normalized:
        if path in files:
            return True
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                return True
    return False


def _ensure_no_suite_jail(command: list[str]) -> list[str]:
    out = [str(item) for item in command]
    return out if "--no-suite-jail" in out else [*out, "--no-suite-jail"]


def _build_jail_env(*, source_repo_root: Path, run_id: str) -> dict[str, str]:
    python = _jail_visible_python(source_repo_root)
    return {"AM_BADGUYS_RUN_ID": run_id, "AM_PATCH_BADGUYS_RUNNER_PYTHON": python}


def _jail_visible_python(repo_root: Path) -> str:
    current = Path(sys.executable)
    if current.is_absolute():
        try:
            relative = current.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return str(current)
        return str(Path("/repo") / relative)
    return str(current)


def _resolve_bind_targets(*, source_repo_root: Path, run_id: str) -> list[_BindTarget]:
    suite_cfg = _load_badguys_suite_cfg(source_repo_root)
    logs_dir = source_repo_root / str(suite_cfg.get("logs_dir", "patches/badguys_logs"))
    central_pattern = str(suite_cfg.get("central_log_pattern", "patches/badguys_{run_id}.log"))
    central = source_repo_root / Path(central_pattern.format(run_id=run_id))
    return [_BindTarget(logs_dir, True), _BindTarget(central, False)]


def _load_badguys_suite_cfg(repo_root: Path) -> dict[str, object]:
    config_path = repo_root / "badguys" / "config.toml"
    raw = tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    suite = raw.get("suite", {})
    return suite if isinstance(suite, dict) else {}


def _prepare_bind_targets(
    *,
    source_repo_root: Path,
    jail_repo_root: Path,
    bind_targets: list[_BindTarget],
) -> None:
    for target in bind_targets:
        host_path = target.path
        jail_path = jail_repo_root / host_path.relative_to(source_repo_root)
        if target.is_dir:
            host_path.mkdir(parents=True, exist_ok=True)
            jail_path.mkdir(parents=True, exist_ok=True)
            continue
        host_path.parent.mkdir(parents=True, exist_ok=True)
        host_path.touch(exist_ok=True)
        jail_path.parent.mkdir(parents=True, exist_ok=True)
        jail_path.touch(exist_ok=True)


def _bootstrap_jail_repo(logger: Any, *, source_repo_root: Path, jail_repo_root: Path) -> None:
    base_sha = _git_stdout(
        logger,
        cwd=source_repo_root,
        argv=["git", "rev-parse", "HEAD"],
        label="unable to resolve source repo HEAD for badguys gate bootstrap",
    )
    _git_stdout(
        logger,
        cwd=source_repo_root,
        argv=["git", "clone", "--no-hardlinks", str(source_repo_root), str(jail_repo_root)],
        label="git clone failed while bootstrapping badguys gate repo",
    )
    origin_repo_root = jail_repo_root / ".git" / "suite_jail_origin.git"
    _git_stdout(
        logger,
        cwd=source_repo_root,
        argv=[
            "git",
            "clone",
            "--bare",
            "--no-hardlinks",
            str(source_repo_root),
            str(origin_repo_root),
        ],
        label="git clone --bare failed while bootstrapping badguys gate origin",
    )
    _git_stdout(
        logger,
        cwd=jail_repo_root,
        argv=["git", "remote", "set-url", "origin", "./.git/suite_jail_origin.git"],
        label="git remote set-url failed while wiring badguys gate origin",
    )
    _git_stdout(
        logger,
        cwd=jail_repo_root,
        argv=["git", "reset", "--hard", base_sha],
        label=f"git reset --hard failed while bootstrapping badguys gate repo at {base_sha}",
    )
    _sync_git_identity(logger, source_repo_root=source_repo_root, jail_repo_root=jail_repo_root)


def _sync_git_identity(logger: Any, *, source_repo_root: Path, jail_repo_root: Path) -> None:
    name = _git_local_config(logger, cwd=source_repo_root, key="user.name")
    email = _git_local_config(logger, cwd=source_repo_root, key="user.email")
    if not (name and email):
        name, email = _FALLBACK_GIT_USER_NAME, _FALLBACK_GIT_USER_EMAIL
    for key, value in (("user.name", name), ("user.email", email)):
        _git_stdout(
            logger,
            cwd=jail_repo_root,
            argv=["git", "config", "--local", key, value],
            label=f"git config --local {key} failed while syncing badguys gate identity",
        )


def _git_local_config(logger: Any, *, cwd: Path, key: str) -> str | None:
    result = logger.run_logged(["git", "config", "--local", "--get", key], cwd=cwd)
    if result.returncode == 0:
        return (result.stdout or "").strip() or None
    if result.returncode == 1:
        return None
    detail = (result.stderr or result.stdout or "").strip() or "command failed"
    raise RunnerError("GATES", "GATES", f"git config --local --get {key} failed: {detail}")


def _git_stdout(logger: Any, *, cwd: Path, argv: list[str], label: str) -> str:
    result = logger.run_logged(argv, cwd=cwd)
    if result.returncode == 0:
        return (result.stdout or "").strip()
    detail = (result.stderr or result.stdout or "").strip() or "command failed"
    raise RunnerError("GATES", "GATES", f"{label}: {detail}")


def _materialize_changed_paths(
    logger: Any,
    *,
    source_repo_root: Path,
    jail_repo_root: Path,
    bind_targets: list[_BindTarget],
) -> None:
    runtime = _require_runtime_context()
    ignored_prefixes, ignored_paths = _internal_ignore_paths(
        source_repo_root=source_repo_root,
        runtime=runtime,
        bind_targets=bind_targets,
    )
    for _status, relpath in changed_path_entries(logger, source_repo_root):
        normalized = _normalize_path(relpath)
        if normalized in ignored_paths:
            continue
        if any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in ignored_prefixes
        ):
            continue
        _materialize_path(
            source_repo_root=source_repo_root,
            jail_repo_root=jail_repo_root,
            relpath=normalized,
        )


def _internal_ignore_paths(
    *,
    source_repo_root: Path,
    runtime: _RuntimeContext,
    bind_targets: list[_BindTarget],
) -> tuple[list[str], set[str]]:
    prefixes: list[str] = []
    paths: set[str] = set()
    for candidate in (runtime.workspaces_dir,):
        try:
            relative = candidate.resolve().relative_to(source_repo_root.resolve())
        except ValueError:
            continue
        prefixes.append(_normalize_path(relative.as_posix()))
    for target in bind_targets:
        try:
            relative = target.path.resolve().relative_to(source_repo_root.resolve())
        except ValueError:
            continue
        normalized = _normalize_path(relative.as_posix())
        if target.is_dir:
            prefixes.append(normalized)
        else:
            paths.add(normalized)
    return prefixes, paths


def _materialize_path(*, source_repo_root: Path, jail_repo_root: Path, relpath: str) -> None:
    source_path = source_repo_root / relpath
    jail_path = jail_repo_root / relpath
    if source_path.is_symlink():
        if jail_path.exists() or jail_path.is_symlink():
            _remove_path(jail_path)
        jail_path.parent.mkdir(parents=True, exist_ok=True)
        jail_path.symlink_to(os.readlink(source_path))
        return
    if source_path.exists():
        if jail_path.exists() or jail_path.is_symlink():
            _remove_path(jail_path)
        jail_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, jail_path)
        return
    _remove_path(jail_path)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _run_badguys_in_jail(
    logger: Any,
    *,
    source_repo_root: Path,
    jail_repo_root: Path,
    bind_targets: list[_BindTarget],
    external_bind_paths: list[Path],
    command: list[str],
    env: dict[str, str],
) -> bool:
    jail_python = str(
        env.get("AM_PATCH_BADGUYS_RUNNER_PYTHON") or _jail_visible_python(source_repo_root)
    )
    cmd = _build_bwrap_cmd(
        source_repo_root=source_repo_root,
        jail_repo_root=jail_repo_root,
        bind_targets=bind_targets,
        external_bind_paths=external_bind_paths,
        argv=[jail_python, "-u", *command],
    )
    return logger.run_logged(cmd, cwd=source_repo_root, env=dict(os.environ, **env)).returncode == 0


def _build_bwrap_cmd(
    *,
    source_repo_root: Path,
    jail_repo_root: Path,
    bind_targets: list[_BindTarget],
    external_bind_paths: list[Path],
    argv: list[str],
) -> list[str]:
    bwrap = _require_bwrap()
    cmd: list[str] = [bwrap, "--die-with-parent", "--new-session", "--proc", "/proc"]
    cmd += ["--dev", "/dev", "--tmpfs", "/tmp"]
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if Path(path).exists():
            cmd += ["--ro-bind", path, path]
    cmd += ["--bind", str(jail_repo_root), "/repo", "--chdir", "/repo"]
    for target in bind_targets:
        jail_target = Path("/repo") / target.path.relative_to(source_repo_root)
        cmd += ["--bind", str(target.path), str(jail_target)]
    for host_path in external_bind_paths:
        for parent in _external_bind_parent_dirs(host_path):
            cmd += ["--dir", parent]
        cmd += ["--ro-bind", str(host_path), str(host_path)]
    cmd += ["--", *argv]
    return cmd


def _find_bwrap() -> str | None:
    env = os.environ.get("AM_PATCH_BWRAP")
    if env is not None:
        value = str(env).strip()
        if not value:
            return None
        if "/" in value or Path(value).is_absolute():
            path = Path(value)
            if path.exists() and path.is_file() and os.access(str(path), os.X_OK):
                return str(path)
            return None
        resolved = shutil.which(value)
        return resolved or None
    return shutil.which("bwrap")


def _require_bwrap() -> str:
    resolved = _find_bwrap()
    if resolved:
        return resolved
    raise RunnerError("GATES", "GATES", _BWRAP_ERROR)


def _external_bind_paths(*, repo_root: Path) -> list[Path]:
    interpreter = Path(sys.executable)
    if interpreter.is_absolute() and _is_under_root(interpreter.resolve(), repo_root.resolve()):
        return []
    user_site = site.getusersitepackages()
    candidates = [user_site] if isinstance(user_site, str) else list(user_site)
    out: list[Path] = []
    seen: set[Path] = set()
    for value in candidates:
        candidate = Path(str(value))
        if not candidate.is_absolute() or not candidate.exists():
            continue
        resolved = candidate.resolve()
        if _is_under_root(resolved, repo_root.resolve()) or resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _external_bind_parent_dirs(path: Path) -> list[str]:
    return [str(parent) for parent in reversed(path.parents) if str(parent) not in {"", "/"}]


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_path(path: str) -> str:
    value = str(path).strip().replace("\\", "/")
    if value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")
