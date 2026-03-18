from __future__ import annotations

import contextlib
import datetime
import os
from pathlib import Path

from .archive import _fsync_dir, _fsync_file, _tmp_path_for_atomic_write
from .errors import RunnerError
from .log import Logger


def _git(logger: Logger, repo: Path, args: list[str]) -> str:
    r = logger.run_logged(["git", *args], cwd=repo, timeout_stage="PREFLIGHT")
    if r.returncode != 0:
        raise RunnerError("PREFLIGHT", "GIT", f"git {' '.join(args)} failed (rc={r.returncode})")
    return (r.stdout or "").strip()


def fetch(logger: Logger, repo: Path) -> None:
    _git(logger, repo, ["fetch", "--prune"])


def current_branch(logger: Logger, repo: Path) -> str:
    return _git(logger, repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def head_sha(logger: Logger, repo: Path) -> str:
    return _git(logger, repo, ["rev-parse", "HEAD"]).strip()


def head_commit_epoch_s(logger: Logger, repo_root: Path) -> int:
    out = _git(logger, repo_root, ["show", "-s", "--format=%ct", "HEAD"]).strip()
    try:
        return int(out)
    except ValueError as err:
        raise RunnerError("PREFLIGHT", "GIT", f"unexpected %ct output: {out!r}") from err


def format_epoch_utc_ts(epoch_s: int) -> str:
    dt = datetime.datetime.fromtimestamp(epoch_s, tz=datetime.UTC)
    return dt.strftime("%Y%m%d_%H%M%S")


def origin_ahead_count(logger: Logger, repo: Path, branch: str) -> int:
    # number of commits in origin/<branch> not in local <branch>
    out = _git(logger, repo, ["rev-list", "--count", f"{branch}..origin/{branch}"])
    try:
        return int(out)
    except ValueError as err:
        raise RunnerError("PREFLIGHT", "GIT", f"unexpected rev-list output: {out!r}") from err


def require_branch(logger: Logger, repo: Path, branch: str) -> None:
    b = current_branch(logger, repo)
    if b != branch:
        raise RunnerError("PREFLIGHT", "GIT", f"must be on branch {branch}, but is {b}")


def require_up_to_date(logger: Logger, repo: Path, branch: str) -> None:
    ahead = origin_ahead_count(logger, repo, branch)
    if ahead > 0:
        raise RunnerError("PREFLIGHT", "GIT", f"origin/{branch} is ahead by {ahead} commits")


def file_diff_since(logger: Logger, repo: Path, base_sha: str, paths: list[str]) -> list[str]:
    # return list of files that changed in repo since base_sha (repo-relative)
    r = logger.run_logged(
        ["git", "diff", "--name-only", f"{base_sha}..HEAD", "--", *paths],
        cwd=repo,
        timeout_stage="PROMOTION",
    )
    if r.returncode != 0:
        raise RunnerError("PROMOTION", "GIT", f"git diff failed (rc={r.returncode})")
    return [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]


def unified_diff_since(logger: Logger, repo: Path, base_sha: str, rel_path: str) -> str:
    """Return unified diff (git apply format) for a single repo-relative path.

    Returns an empty string when there is no diff.
    """
    r = logger.run_logged(
        ["git", "diff", "--no-color", f"{base_sha}..HEAD", "--", rel_path],
        cwd=repo,
        timeout_stage="PROMOTION",
    )
    if r.returncode != 0:
        raise RunnerError("PROMOTION", "GIT", f"git diff failed (rc={r.returncode})")
    return r.stdout or ""


def commit(logger: Logger, repo: Path, message: str, *, stage_all: bool = True) -> str:
    if stage_all:
        r1 = logger.run_logged(
            ["git", "status", "--porcelain"],
            cwd=repo,
            timeout_stage="PROMOTION",
        )
        if r1.returncode != 0:
            raise RunnerError("PROMOTION", "GIT", "git status failed")
        if not (r1.stdout or "").strip():
            raise RunnerError("PROMOTION", "NOOP", "no changes to commit")
        r2 = logger.run_logged(["git", "add", "-A"], cwd=repo, timeout_stage="PROMOTION")
        if r2.returncode != 0:
            raise RunnerError("PROMOTION", "GIT", "git add failed")
    else:
        # Commit only what is already staged (promotion stages files explicitly).
        r_cached = logger.run_logged(
            ["git", "diff", "--cached", "--name-only"],
            cwd=repo,
            timeout_stage="PROMOTION",
        )
        if r_cached.returncode != 0:
            raise RunnerError("PROMOTION", "GIT", "git diff --cached failed")
        if not (r_cached.stdout or "").strip():
            raise RunnerError("PROMOTION", "NOOP", "no staged changes to commit")

    r3 = logger.run_logged(["git", "commit", "-m", message], cwd=repo, timeout_stage="PROMOTION")
    if r3.returncode != 0:
        raise RunnerError("PROMOTION", "GIT", "git commit failed")
    return head_sha(logger, repo)


def push(logger: Logger, repo: Path, branch: str, *, allow_fail: bool = True) -> bool:
    r = logger.run_logged(["git", "push", "origin", branch], cwd=repo, timeout_stage="PROMOTION")
    if r.returncode == 0:
        return True
    if allow_fail:
        logger.warning_core("git_push=FAIL (allowed); local commit remains")
        return False
    raise RunnerError("PROMOTION", "GIT", "git push failed")


def files_changed_since(logger: Logger, repo: Path, base_sha: str, files: list[str]) -> list[str]:
    changed: list[str] = []
    for f in files:
        r = logger.run_logged(
            ["git", "diff", "--name-only", f"{base_sha}..HEAD", "--", f],
            cwd=repo,
            timeout_stage="PROMOTION",
        )
        if r.returncode != 0:
            continue
        if (r.stdout or "").strip():
            changed.append(f)
    return changed


def git_archive(logger: Logger, repo: Path, out_zip: Path, treeish: str = "HEAD") -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = _tmp_path_for_atomic_write(out_zip)
    with contextlib.suppress(FileNotFoundError):
        tmp_path.unlink()

    try:
        r = logger.run_logged(
            ["git", "archive", "--format=zip", "-o", str(tmp_path), treeish],
            cwd=repo,
            timeout_stage="ARCHIVE",
        )
        if r.returncode != 0:
            raise RunnerError("ARCHIVE", "GIT", f"git archive failed (rc={r.returncode})")

        _fsync_file(tmp_path)
        os.replace(tmp_path, out_zip)
        _fsync_dir(out_zip.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()


def commit_changed_files_name_status(
    logger: Logger, repo: Path, commit_sha: str
) -> list[tuple[str, str]]:
    """Return commit file changes as (status, path).

    The returned status is normalized to one of: A, M, D.

    Notes:
    - Renames are represented as (D, old_path) then (A, new_path).
    - Copies are represented as (A, new_path).
    """
    r = logger.run_logged(
        ["git", "show", "--name-status", "--pretty=format:", commit_sha],
        cwd=repo,
        timeout_stage="PROMOTION",
    )
    if r.returncode != 0:
        raise RunnerError("PROMOTION", "GIT", f"git show name-status failed (rc={r.returncode})")

    out: list[tuple[str, str]] = []
    for raw in (r.stdout or "").splitlines():
        line = raw.strip("\n")
        if not line.strip():
            continue

        # Typical formats:
        #   M\tpath
        #   A\tpath
        #   D\tpath
        #   R100\told\tnew
        #   C100\told\tnew
        parts = line.split("\t")
        if not parts:
            continue
        status = parts[0].strip()
        if not status:
            continue

        if status in {"A", "M", "D"}:
            if len(parts) >= 2 and parts[1].strip():
                out.append((status, parts[1].strip()))
            continue

        if status.startswith("R") and len(parts) >= 3:
            old = (parts[1] or "").strip()
            new = (parts[2] or "").strip()
            if old:
                out.append(("D", old))
            if new:
                out.append(("A", new))
            continue

        if status.startswith("C") and len(parts) >= 3:
            new = (parts[2] or "").strip()
            if new:
                out.append(("A", new))
            continue

        # Fall back: treat unknown multi-field status as modify of last path if any.
        if len(parts) >= 2 and parts[-1].strip():
            out.append(("M", parts[-1].strip()))

    return out
