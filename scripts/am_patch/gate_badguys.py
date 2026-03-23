from __future__ import annotations

import os
import shutil
import site
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import RunnerError
from .scope import ChangedPathEntry

DEFAULT_BADGUYS_COMMAND = ["badguys/badguys.py", "-q"]
_FALLBACK_GIT_USER_NAME = "BadGuys Suite Jail"
_FALLBACK_GIT_USER_EMAIL = "badguys-suite-jail@example.invalid"
_BWRAP_ERROR = "FAIL: bwrap not found (install bubblewrap or use --skip-badguys)"


@dataclass(frozen=True)
class _BindSpec:
    host_path: Path
    target_rel: Path
    kind: str


def _normalize_path(value: str) -> str:
    path = str(value).strip().replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    return path.strip("/")


def should_run_badguys(
    *,
    decision_paths: list[str],
    mode: str,
    trigger_prefixes: list[str],
    trigger_files: list[str],
) -> tuple[bool, str]:
    normalized_mode = str(mode or "auto").strip().lower()
    if normalized_mode == "always":
        return True, "always"

    files = {_normalize_path(item) for item in trigger_files if _normalize_path(item)}
    prefixes = [_normalize_path(item) for item in trigger_prefixes if _normalize_path(item)]
    for raw in decision_paths:
        path = _normalize_path(raw)
        if not path:
            continue
        if path in files:
            return True, "trigger_file"
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                return True, "trigger_prefix"
    return False, "no_matching_files"


def append_no_suite_jail(command: list[str]) -> list[str]:
    argv = [str(item) for item in command if str(item).strip()]
    if not argv:
        argv = list(DEFAULT_BADGUYS_COMMAND)
    count = sum(1 for item in argv if item == "--no-suite-jail")
    if count == 0:
        argv.append("--no-suite-jail")
    elif count > 1:
        first = False
        deduped: list[str] = []
        for item in argv:
            if item != "--no-suite-jail":
                deduped.append(item)
                continue
            if not first:
                deduped.append(item)
                first = True
        argv = deduped
    return argv


def resolve_badguys_workspaces_dir(*, repo_root: Path, workspaces_dir: Path | None) -> Path:
    if workspaces_dir is not None:
        return workspaces_dir
    return repo_root / "patches" / "workspaces"


def run_amp_owned_badguys_gate(
    logger: Any,
    cwd: Path,
    *,
    repo_root: Path,
    command: list[str],
    changed_entries: list[ChangedPathEntry],
    workspaces_dir: Path,
    cli_mode: str,
    issue_id: str | int | None,
) -> bool:
    tag = f"{cli_mode}_{issue_id or 'noissue'}"
    jail_root = workspaces_dir / "_badguys_gate" / tag
    jail_repo = jail_root / "repo"
    run_id = os.environ.get("AM_BADGUYS_RUN_ID") or time.strftime("%Y%m%d_%H%M%S")
    ok = False
    created = False
    try:
        if jail_root.exists():
            shutil.rmtree(jail_root, ignore_errors=True)
        jail_root.mkdir(parents=True, exist_ok=True)
        created = True
        _bootstrap_jail_repo(logger=logger, source_repo=cwd, jail_repo=jail_repo)
        bind_specs = _resolve_bind_specs(source_repo=cwd, command=command, run_id=run_id)
        _prepare_binds(jail_repo=jail_repo, bind_specs=bind_specs)
        _materialize_changed_paths(
            source_repo=cwd,
            jail_repo=jail_repo,
            changed_entries=changed_entries,
        )
        external_bind_paths = _external_bind_paths(repo_root=cwd)
        _validate_external_bind_paths(external_bind_paths)
        jail_python = _jail_visible_path(repo_root=cwd, value=sys.executable)
        env = {
            "AM_BADGUYS_SUITE_JAIL_INNER": "1",
            "AM_BADGUYS_RUN_ID": run_id,
            "AM_PATCH_BADGUYS_RUNNER_PYTHON": jail_python,
        }
        inner_argv = [jail_python, "-u", *append_no_suite_jail(command)]
        logger.section("GATE: BADGUYS")
        logger.line(f"badguys_python={jail_python}")
        logger.line(f"badguys_cmd={inner_argv[2:]}")
        bwrap_cmd = _build_bwrap_cmd(
            jail_repo=jail_repo,
            argv=inner_argv,
            bind_specs=bind_specs,
            external_bind_paths=external_bind_paths,
        )
        proc_env = dict(os.environ)
        proc_env.update(env)
        r = logger.run_logged(bwrap_cmd, cwd=cwd, env=proc_env)
        ok = r.returncode == 0
        return ok
    finally:
        if created:
            shutil.rmtree(jail_root, ignore_errors=True)


def find_bwrap() -> str | None:
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
        return shutil.which(value)
    return shutil.which("bwrap")


def _build_bwrap_cmd(
    *,
    jail_repo: Path,
    argv: list[str],
    bind_specs: list[_BindSpec],
    external_bind_paths: list[Path],
) -> list[str]:
    bwrap = find_bwrap()
    if not bwrap:
        raise RunnerError("GATES", "GATES", _BWRAP_ERROR)
    cmd: list[str] = [bwrap, "--die-with-parent", "--new-session"]
    cmd += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if Path(path).exists():
            cmd += ["--ro-bind", path, path]
    cmd += ["--bind", str(jail_repo), "/repo", "--chdir", "/repo"]
    for spec in bind_specs:
        target = Path("/repo") / spec.target_rel
        cmd += ["--bind", str(spec.host_path), str(target)]
    for host_path in external_bind_paths:
        cmd += _external_bind_args(host_path)
    cmd += ["--", *argv]
    return cmd


def _bootstrap_jail_repo(*, logger: Any, source_repo: Path, jail_repo: Path) -> None:
    base_sha = _git_stdout(
        logger=logger,
        cwd=source_repo,
        argv=["git", "rev-parse", "HEAD"],
        label="unable to resolve live repo HEAD for badguys gate bootstrap",
    )
    clone_parent = jail_repo.parent
    clone_parent.mkdir(parents=True, exist_ok=True)
    _git_stdout(
        logger=logger,
        cwd=source_repo,
        argv=["git", "clone", "--no-hardlinks", str(source_repo), str(jail_repo)],
        label="git clone failed while bootstrapping badguys gate repo",
    )
    origin_repo = jail_repo / ".git" / "suite_jail_origin.git"
    _git_stdout(
        logger=logger,
        cwd=source_repo,
        argv=["git", "clone", "--bare", "--no-hardlinks", str(source_repo), str(origin_repo)],
        label="git clone --bare failed while bootstrapping badguys gate origin",
    )
    _git_stdout(
        logger=logger,
        cwd=jail_repo,
        argv=["git", "remote", "set-url", "origin", "./.git/suite_jail_origin.git"],
        label="git remote set-url failed while wiring badguys gate origin",
    )
    _git_stdout(
        logger=logger,
        cwd=jail_repo,
        argv=["git", "reset", "--hard", base_sha],
        label=f"git reset --hard failed while bootstrapping badguys gate repo at {base_sha}",
    )
    _sync_git_identity(logger=logger, source_repo=source_repo, jail_repo=jail_repo)


def _git_stdout(*, logger: Any, cwd: Path, argv: list[str], label: str) -> str:
    r = logger.run_logged(argv, cwd=cwd)
    if r.returncode == 0:
        return (r.stdout or "").strip()
    detail = (r.stderr or r.stdout or "").strip() or "command failed"
    raise RunnerError("GATES", "GATES", f"{label}: {detail}")


def _sync_git_identity(*, logger: Any, source_repo: Path, jail_repo: Path) -> None:
    identity = _resolve_git_identity(logger=logger, source_repo=source_repo)
    for key, value in identity.items():
        _git_stdout(
            logger=logger,
            cwd=jail_repo,
            argv=["git", "config", "--local", key, value],
            label=f"git config --local {key} failed while syncing badguys gate identity",
        )


def _resolve_git_identity(*, logger: Any, source_repo: Path) -> dict[str, str]:
    name = _git_local_config(logger=logger, cwd=source_repo, key="user.name")
    email = _git_local_config(logger=logger, cwd=source_repo, key="user.email")
    if name and email:
        return {"user.name": name, "user.email": email}
    return {"user.name": _FALLBACK_GIT_USER_NAME, "user.email": _FALLBACK_GIT_USER_EMAIL}


def _git_local_config(*, logger: Any, cwd: Path, key: str) -> str | None:
    r = logger.run_logged(["git", "config", "--local", "--get", key], cwd=cwd)
    if r.returncode == 0:
        value = (r.stdout or "").strip()
        return value or None
    if r.returncode == 1:
        return None
    detail = (r.stderr or r.stdout or "").strip() or "command failed"
    raise RunnerError("GATES", "GATES", f"git config --local --get {key} failed: {detail}")


def _resolve_bind_specs(*, source_repo: Path, command: list[str], run_id: str) -> list[_BindSpec]:
    config_path = _resolve_badguys_config_path(source_repo=source_repo, command=command)
    suite = _load_badguys_suite_config(config_path)
    logs_dir = str(suite.get("logs_dir", "patches/badguys_logs"))
    central_pattern = str(suite.get("central_log_pattern", "patches/badguys_{run_id}.log"))
    specs = [
        _make_bind_spec(source_repo=source_repo, value=logs_dir, kind="dir"),
        _make_bind_spec(
            source_repo=source_repo,
            value=central_pattern.replace("{run_id}", run_id),
            kind="file",
        ),
    ]
    deduped: dict[Path, _BindSpec] = {}
    for spec in specs:
        prev = deduped.get(spec.target_rel)
        if prev is None:
            deduped[spec.target_rel] = spec
            continue
        if prev.kind != spec.kind:
            target = spec.target_rel.as_posix()
            raise RunnerError("GATES", "GATES", f"conflicting bind kinds for target: {target}")
    return list(deduped.values())


def _make_bind_spec(*, source_repo: Path, value: str, kind: str) -> _BindSpec:
    category = "logs_dir" if kind == "dir" else "central_log_pattern"
    host_path = _config_path_to_host_path(
        source_repo=source_repo,
        value=value,
        category=category,
    )
    target_rel = _repo_relative_path(repo_root=source_repo, host_path=host_path)
    return _BindSpec(host_path=host_path, target_rel=target_rel, kind=kind)


def _resolve_badguys_config_path(*, source_repo: Path, command: list[str]) -> Path:
    argv = append_no_suite_jail(command)
    for idx, item in enumerate(argv):
        if item != "--config":
            continue
        if idx + 1 >= len(argv):
            break
        return _config_path_to_host_path(
            source_repo=source_repo,
            value=argv[idx + 1],
            category="config",
        )
    return source_repo / "badguys" / "config.toml"


def _load_badguys_suite_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        return {}
    with config_path.open("rb") as fh:
        data = tomllib.load(fh)
    suite = data.get("suite")
    return suite if isinstance(suite, dict) else {}


def _config_path_to_host_path(*, source_repo: Path, value: str, category: str) -> Path:
    candidate = Path(str(value))
    error = f"{category} path must be repo-relative: {candidate}"
    if candidate.is_absolute():
        raise RunnerError("GATES", "GATES", error)
    resolved_root = source_repo.resolve()
    resolved_host = (source_repo / candidate).resolve(strict=False)
    try:
        resolved_host.relative_to(resolved_root)
    except ValueError as exc:
        raise RunnerError("GATES", "GATES", error) from exc
    return resolved_host


def _prepare_binds(*, jail_repo: Path, bind_specs: list[_BindSpec]) -> None:
    for spec in bind_specs:
        _prepare_host_bind_source(spec)
        target = jail_repo / spec.target_rel
        if spec.kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)


def _prepare_host_bind_source(spec: _BindSpec) -> None:
    try:
        if spec.kind == "dir":
            spec.host_path.mkdir(parents=True, exist_ok=True)
            return
        spec.host_path.parent.mkdir(parents=True, exist_ok=True)
        spec.host_path.touch(exist_ok=True)
    except OSError as exc:
        target = spec.target_rel.as_posix()
        raise RunnerError(
            "GATES",
            "GATES",
            f"unable to prepare bind source for {target}: {exc}",
        ) from exc


def _repo_relative_path(*, repo_root: Path, host_path: Path) -> Path:
    resolved_root = repo_root.resolve()
    resolved_host = host_path.resolve() if host_path.exists() else host_path.resolve(strict=False)
    try:
        return resolved_host.relative_to(resolved_root)
    except ValueError as exc:
        raise RunnerError("GATES", "GATES", f"bind path outside repo root: {host_path}") from exc


def _materialize_changed_paths(
    *,
    source_repo: Path,
    jail_repo: Path,
    changed_entries: list[ChangedPathEntry],
) -> None:
    seen: set[str] = set()
    for _status, rel in changed_entries:
        path = _normalize_path(rel)
        if not path or path in seen:
            continue
        seen.add(path)
        src = source_repo / path
        dst = jail_repo / path
        if src.exists() or src.is_symlink():
            _copy_path(src=src, dst=dst)
        else:
            _remove_path(dst)


def _copy_path(*, src: Path, dst: Path) -> None:
    if src.is_symlink():
        dst.parent.mkdir(parents=True, exist_ok=True)
        _remove_path(dst)
        dst.symlink_to(os.readlink(src))
        return
    if src.is_dir():
        _remove_path(dst)
        shutil.copytree(src, dst, symlinks=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst, follow_symlinks=False)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _external_bind_paths(*, repo_root: Path) -> list[Path]:
    python_path = Path(sys.executable)
    resolved_root = repo_root.resolve()
    if python_path.is_absolute() and _path_is_under_root(python_path.resolve(), resolved_root):
        return []
    candidates = site.getusersitepackages()
    values = [candidates] if isinstance(candidates, str) else list(candidates)
    seen: set[Path] = set()
    out: list[Path] = []
    for value in values:
        candidate = Path(str(value))
        if not candidate.is_absolute() or not candidate.exists() or not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved in seen or _path_is_under_root(resolved, resolved_root):
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _path_is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_external_bind_paths(paths: list[Path]) -> None:
    for host_path in paths:
        resolved = host_path.resolve()
        if not resolved.is_absolute() or not resolved.exists() or not resolved.is_dir():
            raise RunnerError("GATES", "GATES", f"invalid external bind path: {host_path}")


def _external_bind_args(host_path: Path) -> list[str]:
    resolved = host_path.resolve()
    args: list[str] = []
    for parent in reversed(resolved.parents):
        parent_str = str(parent)
        if not parent_str or parent_str == "/":
            continue
        args += ["--dir", parent_str]
    args += ["--ro-bind", str(resolved), str(resolved)]
    return args


def _jail_visible_path(*, repo_root: Path, value: str) -> str:
    candidate = Path(str(value))
    if not candidate.is_absolute():
        return str(value)
    try:
        relative = candidate.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return str(candidate)
    return str(Path("/repo") / relative)
