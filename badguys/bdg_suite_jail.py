from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SuiteJail:
    root: Path
    repo_root: Path


_BWRAP_ERROR = "FAIL: bwrap not found (install bubblewrap or use --no-suite-jail)"


def suite_jail_root(host_repo_root: Path, issue_id: str) -> Path:
    return host_repo_root / "patches" / "badguys_suite_jail" / f"issue_{issue_id}"


def suite_jail_repo_root(host_repo_root: Path, issue_id: str) -> Path:
    return suite_jail_root(host_repo_root, issue_id) / "repo"


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
        resolved = shutil.which(value)
        return resolved or None
    return shutil.which("bwrap")


def require_bwrap() -> str:
    resolved = find_bwrap()
    if resolved:
        return resolved
    raise SystemExit(_BWRAP_ERROR)


def prepare_suite_jail(
    *,
    host_repo_root: Path,
    issue_id: str,
    host_bind_paths: Iterable[Path],
) -> SuiteJail:
    root = suite_jail_root(host_repo_root, issue_id)
    repo_root = root / "repo"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    _bootstrap_jail_repo(host_repo_root=host_repo_root, repo_root=repo_root)
    _prepare_bind_targets(
        host_repo_root=host_repo_root,
        jail_repo_root=repo_root,
        host_bind_paths=host_bind_paths,
    )
    return SuiteJail(root=root, repo_root=repo_root)


def build_bwrap_cmd(
    *,
    host_repo_root: Path,
    jail_repo_root: Path,
    argv: list[str],
    host_bind_paths: Iterable[Path],
) -> list[str]:
    bwrap = require_bwrap()
    cmd: list[str] = [bwrap, "--die-with-parent", "--new-session"]
    cmd += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if Path(path).exists():
            cmd += ["--ro-bind", path, path]
    cmd += ["--bind", str(jail_repo_root), "/repo", "--chdir", "/repo"]
    for host_path in host_bind_paths:
        target = Path("/repo") / _repo_relative_path(
            host_repo_root=host_repo_root,
            host_path=host_path,
        )
        cmd += ["--bind", str(host_path), str(target)]
    cmd += ["--"] + list(argv)
    return cmd


def run_in_suite_jail(
    *,
    host_repo_root: Path,
    jail_repo_root: Path,
    argv: list[str],
    host_bind_paths: Iterable[Path],
    env: dict[str, str],
) -> int:
    cmd = build_bwrap_cmd(
        host_repo_root=host_repo_root,
        jail_repo_root=jail_repo_root,
        argv=argv,
        host_bind_paths=host_bind_paths,
    )
    completed = subprocess.run(cmd, env=env, check=False)
    return int(completed.returncode)


def teardown_suite_jail(host_repo_root: Path, issue_id: str) -> None:
    shutil.rmtree(suite_jail_root(host_repo_root, issue_id), ignore_errors=True)


def _bootstrap_jail_repo(*, host_repo_root: Path, repo_root: Path) -> None:
    base_sha = _git_stdout(
        cwd=host_repo_root,
        argv=["git", "rev-parse", "HEAD"],
        label="unable to resolve live repo HEAD for suite jail bootstrap",
    )
    _git_stdout(
        cwd=host_repo_root,
        argv=["git", "clone", "--no-hardlinks", str(host_repo_root), str(repo_root)],
        label="git clone failed while bootstrapping suite jail repo",
    )
    origin_repo_root = _suite_jail_origin_repo_root(repo_root)
    _git_stdout(
        cwd=host_repo_root,
        argv=[
            "git",
            "clone",
            "--bare",
            "--no-hardlinks",
            str(host_repo_root),
            str(origin_repo_root),
        ],
        label="git clone --bare failed while bootstrapping suite jail origin",
    )
    _git_stdout(
        cwd=repo_root,
        argv=["git", "remote", "set-url", "origin", "./.git/suite_jail_origin.git"],
        label="git remote set-url failed while wiring suite jail origin",
    )
    _git_stdout(
        cwd=repo_root,
        argv=["git", "reset", "--hard", base_sha],
        label=(f"git reset --hard failed while bootstrapping suite jail repo at {base_sha}"),
    )
    _sync_local_git_identity(host_repo_root=host_repo_root, repo_root=repo_root)


def _suite_jail_origin_repo_root(repo_root: Path) -> Path:
    return repo_root / ".git" / "suite_jail_origin.git"


def _sync_local_git_identity(*, host_repo_root: Path, repo_root: Path) -> None:
    for key in ("user.name", "user.email"):
        value = _git_local_config(cwd=host_repo_root, key=key)
        if value is None:
            continue
        _git_stdout(
            cwd=repo_root,
            argv=["git", "config", "--local", key, value],
            label=f"git config failed while syncing suite jail {key}",
        )


def _git_local_config(*, cwd: Path, key: str) -> str | None:
    proc = subprocess.run(
        ["git", "config", "--local", "--get", key],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return (proc.stdout or "").strip()
    return None


def _git_stdout(*, cwd: Path, argv: list[str], label: str) -> str:
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return (proc.stdout or "").strip()
    detail = (proc.stderr or proc.stdout or "").strip()
    if not detail:
        detail = "command failed"
    raise SystemExit(f"FAIL: suite jail: {label}: {detail}")


def _prepare_bind_targets(
    *,
    host_repo_root: Path,
    jail_repo_root: Path,
    host_bind_paths: Iterable[Path],
) -> None:
    for host_path in host_bind_paths:
        target = jail_repo_root / _repo_relative_path(
            host_repo_root=host_repo_root,
            host_path=host_path,
        )
        if host_path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()


def _repo_relative_path(*, host_repo_root: Path, host_path: Path) -> Path:
    resolved_host = host_path.resolve()
    resolved_root = host_repo_root.resolve()
    try:
        return resolved_host.relative_to(resolved_root)
    except ValueError as exc:
        raise SystemExit(f"FAIL: suite jail bind path outside repo root: {host_path}") from exc
