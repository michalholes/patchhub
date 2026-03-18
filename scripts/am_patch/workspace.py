from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import RunnerError
from .log import Logger


@dataclass
class Workspace:
    root: Path
    repo: Path
    meta_path: Path
    base_sha: str
    attempt: int
    message: str | None
    target_repo_name: str | None


@dataclass
class WorkspaceCheckpoint:
    kind: str  # 'clean' | 'stash'
    # A git stash reference name (e.g. 'stash@{0}') that represents the pre-patch
    # state (kind='stash').
    stash_ref: str | None = None


def _read_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.exists():
        return {}
    try:
        obj = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {}
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out[str(k)] = v
        return out
    except Exception:
        return {}


def _write_meta(meta_path: Path, meta: dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")


def _workspace_paths(
    workspaces_dir: Path,
    issue_id: str,
    *,
    issue_dir_template: str,
    repo_dir_name: str,
    meta_filename: str,
) -> tuple[Path, Path, Path]:
    ws_root = workspaces_dir / issue_dir_template.format(issue=issue_id)
    repo_dir = ws_root / repo_dir_name
    meta_path = ws_root / meta_filename
    return ws_root, repo_dir, meta_path


def _read_workspace_meta_strict(meta_path: Path) -> dict[str, Any]:
    if not meta_path.exists():
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            f"workspace meta.json not found: {meta_path}",
        )
    try:
        obj = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            f"workspace meta.json is invalid: {meta_path}",
        ) from exc
    if not isinstance(obj, dict):
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            f"workspace meta.json must contain a JSON object: {meta_path}",
        )
    out: dict[str, Any] = {}
    for key, value in obj.items():
        out[str(key)] = value
    return out


def _meta_attempt(meta: dict[str, Any]) -> int:
    value = meta.get("attempt", 0)
    try:
        return int(value)
    except Exception as exc:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace meta.json has invalid attempt",
        ) from exc


def _meta_base_sha(meta: dict[str, Any]) -> str:
    value = meta.get("base_sha", "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace meta.json has invalid base_sha",
        )
    return value


def _meta_message(meta: dict[str, Any]) -> str | None:
    value = meta.get("message")
    if value is None:
        return None
    if not isinstance(value, str):
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace meta.json has invalid message",
        )
    return value


def _validate_target_repo_name(value: Any) -> str:
    if not isinstance(value, str):
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace meta.json has invalid target_repo_name",
        )
    token = value.strip()
    if not token:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace meta.json has invalid target_repo_name",
        )
    if "\n" in token or "\r" in token:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace meta.json has invalid target_repo_name",
        )
    if any(ch.isspace() for ch in token) or "/" in token or "\\" in token:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace meta.json has invalid target_repo_name",
        )
    try:
        token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace meta.json has invalid target_repo_name",
        ) from exc
    return token


def _target_repo_name_from_canonical_path(path: Path, *, field: str) -> str:
    resolved = path.resolve()
    parts = resolved.parts
    if len(parts) != 4 or parts[:3] != ("/", "home", "pi"):
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            f"{field} must canonically resolve to /home/pi/<name>",
        )
    return _validate_target_repo_name(parts[3])


def _try_target_repo_name_from_path(path: Path) -> str | None:
    try:
        return _target_repo_name_from_canonical_path(path, field="path")
    except RunnerError:
        return None


def _target_repo_name_from_origin(origin: str, *, field: str) -> str:
    raw = str(origin).strip()
    if not raw:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            f"{field} is missing",
        )
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        if parsed.netloc not in ("", "localhost"):
            raise RunnerError(
                "PREFLIGHT",
                "WORKSPACE",
                f"{field} must use file:///home/pi/<name> or /home/pi/<name>",
            )
        raw = unquote(parsed.path)
    elif "://" in raw:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            f"{field} must use file:///home/pi/<name> or /home/pi/<name>",
        )
    return _target_repo_name_from_canonical_path(Path(raw), field=field)


def _read_repo_origin_url(
    repo_dir: Path,
    *,
    logger: Logger | None,
    timeout_s: int,
) -> str:
    argv = ["git", "config", "--get", "remote.origin.url"]
    if logger is not None:
        result = logger.run_logged(argv, cwd=repo_dir, timeout_s=timeout_s)
        if result.returncode != 0:
            raise RunnerError(
                "PREFLIGHT",
                "WORKSPACE",
                "workspace clone origin is unavailable for target migration",
            )
        return (result.stdout or "").strip()
    try:
        completed = subprocess.run(
            argv,
            cwd=repo_dir,
            text=True,
            capture_output=True,
            timeout=(timeout_s if timeout_s > 0 else None),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace clone origin lookup timed out during target migration",
        ) from exc
    except Exception as exc:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace clone origin lookup failed during target migration",
        ) from exc
    if completed.returncode != 0:
        raise RunnerError(
            "PREFLIGHT",
            "WORKSPACE",
            "workspace clone origin is unavailable for target migration",
        )
    return (completed.stdout or "").strip()


def load_or_migrate_workspace_target_repo_name(
    workspaces_dir: Path,
    issue_id: str,
    *,
    issue_dir_template: str = "issue_{issue}",
    repo_dir_name: str = "repo",
    meta_filename: str = "meta.json",
    logger: Logger | None = None,
    timeout_s: int = 0,
    write_back: bool = True,
) -> str:
    ws_root, repo_dir, meta_path = _workspace_paths(
        workspaces_dir,
        issue_id,
        issue_dir_template=issue_dir_template,
        repo_dir_name=repo_dir_name,
        meta_filename=meta_filename,
    )
    if not repo_dir.exists():
        raise RunnerError("PREFLIGHT", "WORKSPACE", f"workspace not found: {repo_dir}")
    meta = _read_workspace_meta_strict(meta_path)
    target_value = meta.get("target_repo_name")
    if target_value is not None:
        return _validate_target_repo_name(target_value)
    origin = _read_repo_origin_url(repo_dir, logger=logger, timeout_s=timeout_s)
    target_repo_name = _target_repo_name_from_origin(
        origin,
        field="workspace clone origin",
    )
    if write_back:
        meta["target_repo_name"] = target_repo_name
        _write_meta(meta_path, meta)
    return target_repo_name


def _expected_workspace_target_repo_name(
    live_repo: Path,
    *,
    logger: Logger,
) -> str:
    direct = _try_target_repo_name_from_path(live_repo)
    if direct is not None:
        return direct
    origin = _read_repo_origin_url(live_repo, logger=logger, timeout_s=0)
    return _target_repo_name_from_origin(origin, field="live repository origin")


def open_existing_workspace(
    logger: Logger,
    workspaces_dir: Path,
    issue_id: str,
    *,
    issue_dir_template: str = "issue_{issue}",
    repo_dir_name: str = "repo",
    meta_filename: str = "meta.json",
) -> Workspace:
    ws_root, repo_dir, meta_path = _workspace_paths(
        workspaces_dir,
        issue_id,
        issue_dir_template=issue_dir_template,
        repo_dir_name=repo_dir_name,
        meta_filename=meta_filename,
    )
    if not repo_dir.exists():
        raise RunnerError("PREFLIGHT", "WORKSPACE", f"workspace not found: {repo_dir}")
    meta = _read_workspace_meta_strict(meta_path)
    target_value = meta.get("target_repo_name")
    if target_value is None:
        target_repo_name = load_or_migrate_workspace_target_repo_name(
            workspaces_dir,
            issue_id,
            issue_dir_template=issue_dir_template,
            repo_dir_name=repo_dir_name,
            meta_filename=meta_filename,
            logger=logger,
            write_back=True,
        )
        meta = _read_workspace_meta_strict(meta_path)
    else:
        target_repo_name = _validate_target_repo_name(target_value)
    return Workspace(
        root=ws_root,
        repo=repo_dir,
        meta_path=meta_path,
        base_sha=_meta_base_sha(meta),
        attempt=_meta_attempt(meta),
        message=_meta_message(meta),
        target_repo_name=target_repo_name,
    )


def bump_existing_workspace_attempt(meta_path: Path) -> int:
    meta = _read_workspace_meta_strict(meta_path)
    new_attempt = _meta_attempt(meta) + 1
    meta["attempt"] = new_attempt
    _write_meta(meta_path, meta)
    return new_attempt


def ensure_workspace(
    logger: Logger,
    workspaces_dir: Path,
    issue_id: str,
    live_repo: Path,
    base_sha: str,
    update: bool,
    soft_reset: bool,
    message: str | None,
    *,
    issue_dir_template: str = "issue_{issue}",
    repo_dir_name: str = "repo",
    meta_filename: str = "meta.json",
    history_logs_dir: str = "logs",
    history_oldlogs_dir: str = "oldlogs",
    history_patches_dir: str = "patches",
    history_oldpatches_dir: str = "oldpatches",
) -> Workspace:
    ws_root = workspaces_dir / issue_dir_template.format(issue=issue_id)
    repo_dir = ws_root / repo_dir_name
    meta_path = ws_root / meta_filename

    # Per-issue history (kept until workspace deletion on successful runs).
    # - logs/: current run log only
    # - oldlogs/: prior run logs
    # - patches/: current run patch script only
    # - oldpatches/: prior run patch scripts
    (ws_root / history_logs_dir).mkdir(parents=True, exist_ok=True)
    (ws_root / history_oldlogs_dir).mkdir(parents=True, exist_ok=True)
    (ws_root / history_patches_dir).mkdir(parents=True, exist_ok=True)
    (ws_root / history_oldpatches_dir).mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {}
    if repo_dir.exists():
        meta = _read_workspace_meta_strict(meta_path)
    attempt = _meta_attempt(meta) + 1 if meta else 1

    if not repo_dir.exists():
        logger.section("WORKSPACE CREATE")
        logger.info_core(f"workspace=create issue={issue_id} base_sha={base_sha}")
        ws_root.mkdir(parents=True, exist_ok=True)
        r = logger.run_logged(["git", "clone", str(live_repo), str(repo_dir)])
        if r.returncode != 0:
            raise RunnerError("PREFLIGHT", "GIT", "git clone failed while creating workspace")
        r2 = logger.run_logged(["git", "checkout", base_sha], cwd=repo_dir)
        if r2.returncode != 0:
            raise RunnerError("PREFLIGHT", "GIT", f"git checkout {base_sha} failed in workspace")

        target_repo_name = _expected_workspace_target_repo_name(live_repo, logger=logger)
        meta = {
            "base_sha": base_sha,
            "attempt": attempt,
            "message": message,
            "target_repo_name": target_repo_name,
        }
        _write_meta(meta_path, meta)
    else:
        logger.section("WORKSPACE REUSE")
        logger.info_core(f"workspace=reuse issue={issue_id} base_sha={base_sha}")
        expected_target_repo_name = _expected_workspace_target_repo_name(live_repo, logger=logger)
        persisted_target_repo_name = load_or_migrate_workspace_target_repo_name(
            workspaces_dir,
            issue_id,
            issue_dir_template=issue_dir_template,
            repo_dir_name=repo_dir_name,
            meta_filename=meta_filename,
            logger=logger,
            write_back=True,
        )
        if persisted_target_repo_name != expected_target_repo_name:
            raise RunnerError(
                "PREFLIGHT",
                "WORKSPACE",
                "workspace target_repo_name does not match selected live target",
            )
        meta.setdefault("message", meta.get("message"))
        persisted = _meta_base_sha(meta) or base_sha

        if soft_reset:
            r = logger.run_logged(["git", "reset", "--hard", persisted], cwd=repo_dir)
            if r.returncode != 0:
                raise RunnerError("PREFLIGHT", "GIT", "workspace soft reset failed")
            r2 = logger.run_logged(["git", "clean", "-fdx"], cwd=repo_dir)
            if r2.returncode != 0:
                raise RunnerError("PREFLIGHT", "GIT", "workspace clean failed")

        if update:
            r = logger.run_logged(["git", "fetch", "--prune"], cwd=repo_dir)
            if r.returncode != 0:
                raise RunnerError("PREFLIGHT", "GIT", "workspace fetch failed")
            r2 = logger.run_logged(["git", "reset", "--hard", base_sha], cwd=repo_dir)
            if r2.returncode != 0:
                raise RunnerError("PREFLIGHT", "GIT", "workspace update reset failed")
            persisted = base_sha

        meta["base_sha"] = persisted
        meta["attempt"] = attempt
        _write_meta(meta_path, meta)

    meta2 = _read_workspace_meta_strict(meta_path)
    target_value = meta2.get("target_repo_name")
    return Workspace(
        root=ws_root,
        repo=repo_dir,
        meta_path=meta_path,
        base_sha=_meta_base_sha(meta2) or base_sha,
        attempt=attempt,
        message=_meta_message(meta2),
        target_repo_name=(
            _validate_target_repo_name(target_value) if target_value is not None else None
        ),
    )


def delete_workspace(logger: Logger, ws: Workspace) -> None:
    logger.section("WORKSPACE DELETE")
    logger.info_core(f"workspace=delete root={ws.root}")
    shutil.rmtree(ws.root, ignore_errors=True)


def create_checkpoint(logger: Logger, repo: Path, *, enabled: bool) -> WorkspaceCheckpoint | None:
    if not enabled:
        logger.section("WORKSPACE CHECKPOINT")
        logger.warning_core("checkpoint=SKIP (disabled)")
        return None

    logger.section("WORKSPACE CHECKPOINT")

    # If workspace is clean, do not create a stash; rollback can restore via reset+clean.
    r0 = logger.run_logged(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo)
    if r0.returncode != 0:
        raise RunnerError("PREFLIGHT", "GIT", "failed to read workspace status for checkpoint")
    if not (r0.stdout or "").strip():
        logger.line("checkpoint=CLEAN (workspace clean; no stash)")
        logger.info_core("checkpoint=CLEAN")
        return WorkspaceCheckpoint(kind="clean")

    # Workspace is dirty: capture complete state including untracked; then immediately
    # re-apply so the user state remains.
    marker = "am_patch_checkpoint"
    r1 = logger.run_logged(["git", "stash", "push", "-u", "-m", marker], cwd=repo)
    if r1.returncode != 0:
        raise RunnerError(
            "PREFLIGHT", "GIT", "failed to create workspace checkpoint (git stash push)"
        )

    # Identify the created stash ref.
    r2 = logger.run_logged(["git", "stash", "list"], cwd=repo)
    if r2.returncode != 0:
        raise RunnerError("PREFLIGHT", "GIT", "failed to list workspace stashes")
    lines = [ln.strip() for ln in (r2.stdout or "").splitlines() if ln.strip()]
    stash_ref: str | None = None
    for ln in lines:
        if marker in ln:
            stash_ref = ln.split(":", 1)[0].strip()
            break
    if not stash_ref:
        raise RunnerError("PREFLIGHT", "GIT", "workspace checkpoint stash not found after creation")

    # Restore state (stash remains for later rollback).
    r3 = logger.run_logged(["git", "stash", "apply", "--index", stash_ref], cwd=repo)
    if r3.returncode != 0:
        raise RunnerError("PREFLIGHT", "GIT", "failed to re-apply workspace checkpoint stash")

    logger.line(f"checkpoint_stash_ref={stash_ref}")
    logger.info_core(f"checkpoint=STASH ref={stash_ref}")
    return WorkspaceCheckpoint(kind="stash", stash_ref=stash_ref)


def drop_checkpoint(logger: Logger, repo: Path, ckpt: WorkspaceCheckpoint | None) -> None:
    if not ckpt:
        return
    if ckpt.kind != "stash" or not ckpt.stash_ref:
        return
    logger.section("WORKSPACE CHECKPOINT DROP")
    _ = logger.run_logged(
        ["git", "stash", "drop", ckpt.stash_ref],
        cwd=repo,
        timeout_hard_fail=False,
    )


def rollback_to_checkpoint(logger: Logger, repo: Path, ckpt: WorkspaceCheckpoint | None) -> None:
    if not ckpt:
        logger.section("WORKSPACE ROLLBACK")
        logger.info_core("rollback=SKIP (no checkpoint)")
        return

    logger.section("WORKSPACE ROLLBACK")
    logger.line(f"rollback_kind={ckpt.kind!r}")
    logger.info_core(f"rollback_kind={ckpt.kind}")

    r1 = logger.run_logged(["git", "reset", "--hard"], cwd=repo)
    if r1.returncode != 0:
        raise RunnerError("ROLLBACK", "GIT", "git reset --hard failed during rollback")
    r2 = logger.run_logged(["git", "clean", "-fd"], cwd=repo)
    if r2.returncode != 0:
        raise RunnerError("ROLLBACK", "GIT", "git clean -fd failed during rollback")
    if ckpt.kind == "stash":
        if not ckpt.stash_ref:
            raise RunnerError("ROLLBACK", "GIT", "missing stash_ref for stash checkpoint")
        logger.line(f"rollback_to={ckpt.stash_ref}")
        r3 = logger.run_logged(["git", "stash", "apply", "--index", ckpt.stash_ref], cwd=repo)
        if r3.returncode != 0:
            raise RunnerError("ROLLBACK", "GIT", "git stash apply failed during rollback")
        _ = logger.run_logged(
            ["git", "stash", "drop", ckpt.stash_ref],
            cwd=repo,
            timeout_hard_fail=False,
        )
    else:
        logger.line("rollback_to=CLEAN (reset+clean only)")
