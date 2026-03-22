from __future__ import annotations

import contextlib
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch.archive import _fsync_dir, _fsync_file, _tmp_path_for_atomic_write
from am_patch.errors import RunnerError

__all__ = [
    "InitialSelfBackupResult",
    "maybe_create_initial_self_backup",
    "normalize_self_backup_policy",
]


@dataclass(frozen=True)
class InitialSelfBackupResult:
    created: bool
    skip_reason: str | None
    zip_path: Path | None
    archived_files: tuple[str, ...]
    self_target: bool


def _normalize_relpath(raw: str) -> str:
    text = str(raw).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _workspace_repo_dir(
    *,
    workspaces_dir: Path,
    issue_id: str,
    issue_dir_template: str,
    repo_dir_name: str,
) -> Path:
    return workspaces_dir / issue_dir_template.format(issue=issue_id) / repo_dir_name


def _tracked_files(*, logger: Any, runner_root: Path) -> list[str]:
    result = logger.run_logged(
        ["git", "ls-files", "-z"],
        cwd=runner_root,
        timeout_stage="PREFLIGHT",
    )
    if result.returncode != 0:
        raise RunnerError(
            "PREFLIGHT",
            "GIT",
            "git ls-files failed while building initial self-backup",
        )
    seen: set[str] = set()
    tracked: list[str] = []
    for item in (result.stdout or "").split("\0"):
        rel = _normalize_relpath(item)
        if not rel or rel in seen:
            continue
        seen.add(rel)
        tracked.append(rel)
    tracked.sort()
    return tracked


def _resolve_archived_files(
    *,
    logger: Any,
    runner_root: Path,
    include_relpaths: list[str],
) -> tuple[str, ...]:
    tracked = _tracked_files(logger=logger, runner_root=runner_root)
    tracked_set = set(tracked)
    archived: set[str] = set()
    runner_root_resolved = runner_root.resolve()

    for raw_entry in include_relpaths:
        rel = _normalize_relpath(raw_entry)
        if not rel:
            continue
        candidate = (runner_root / rel).resolve()
        try:
            candidate.relative_to(runner_root_resolved)
        except ValueError as exc:
            raise RunnerError(
                "PREFLIGHT",
                "CONFIG",
                (f"self_backup_include_relpaths entry resolves outside runner_root: {raw_entry!r}"),
            ) from exc
        if candidate.is_file():
            if rel not in tracked_set:
                raise RunnerError(
                    "PREFLIGHT",
                    "GIT",
                    f"self_backup include path is not git-tracked: {rel}",
                )
            archived.add(rel)
            continue
        if candidate.is_dir():
            prefix = rel + "/"
            matches = [path for path in tracked if path.startswith(prefix)]
            if not matches:
                raise RunnerError(
                    "PREFLIGHT",
                    "GIT",
                    f"self_backup include directory has no git-tracked files: {rel}",
                )
            archived.update(matches)
            continue
        raise RunnerError(
            "PREFLIGHT",
            "CONFIG",
            f"self_backup include path does not exist under runner_root: {rel}",
        )

    return tuple(sorted(archived))


def _render_backup_name(*, policy: Any, issue_id: str) -> str:
    template = str(getattr(policy, "self_backup_template", "")).strip()
    ts_format = str(getattr(policy, "log_ts_format", "%Y%m%d_%H%M%S"))
    try:
        rendered = template.format(issue=issue_id, ts=time.strftime(ts_format))
    except Exception as exc:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"invalid self_backup_template: {template!r} ({exc!r})",
        ) from exc
    name = Path(rendered).name
    if name != rendered or not name:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "self_backup_template must render to a basename",
        )
    return name


def normalize_self_backup_policy(policy: Any) -> None:
    mode = str(getattr(policy, "self_backup_mode", "initial_self_patch")).strip()
    if mode not in ("never", "initial_self_patch"):
        raise RunnerError("CONFIG", "INVALID", f"invalid self_backup_mode={mode!r}")
    raw_dir = str(getattr(policy, "self_backup_dir", "quarantine")).replace("\\", "/").strip()
    parts = [part for part in raw_dir.split("/") if part not in ("", ".")]
    if not parts or ".." in parts or raw_dir.startswith("/"):
        raise RunnerError("CONFIG", "INVALID", f"invalid self_backup_dir={raw_dir!r}")
    if len(raw_dir) > 2 and raw_dir[1:3] == ":/":
        raise RunnerError("CONFIG", "INVALID", f"invalid self_backup_dir={raw_dir!r}")
    template = str(getattr(policy, "self_backup_template", "")).strip()
    if not template or Path(template).name != template:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"self_backup_template must be a basename: {template!r}",
        )
    try:
        rendered = template.format(issue="1", ts="x")
    except Exception as e:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"invalid self_backup_template: {template!r} ({e!r})",
        ) from e
    if not rendered or Path(rendered).name != rendered:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"self_backup_template must render to a basename: {rendered!r}",
        )
    policy.self_backup_mode = mode
    policy.self_backup_dir = "/".join(parts)
    policy.self_backup_template = template
    policy.self_backup_include_relpaths = [
        s
        for item in getattr(policy, "self_backup_include_relpaths", [])
        if (s := str(item).strip())
    ]


def _write_backup_zip(
    *,
    artifacts_root: Path,
    self_backup_dir: str,
    zip_name: str,
    runner_root: Path,
    archived_files: tuple[str, ...],
) -> Path:
    zip_path = artifacts_root / self_backup_dir / zip_name
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_path_for_atomic_write(zip_path)
    with contextlib.suppress(FileNotFoundError):
        tmp_path.unlink()
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rel in archived_files:
                src = runner_root / rel
                if not src.is_file():
                    raise RunnerError(
                        "PREFLIGHT",
                        "FS",
                        f"initial self-backup source missing during write: {rel}",
                    )
                zf.write(src, arcname=rel)
        _fsync_file(tmp_path)
        tmp_path.replace(zip_path)
        _fsync_dir(zip_path.parent)
    except RunnerError:
        raise
    except Exception as exc:
        raise RunnerError(
            "PREFLIGHT",
            "FS",
            f"initial self-backup write failed: {exc}",
        ) from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
    return zip_path


def maybe_create_initial_self_backup(
    *,
    logger: Any,
    policy: Any,
    issue_id: str,
    runner_root: Path,
    live_target_root: Path,
    artifacts_root: Path,
    workspaces_dir: Path,
    issue_dir_template: str,
    repo_dir_name: str,
) -> InitialSelfBackupResult:
    runner_root = runner_root.resolve()
    live_target_root = live_target_root.resolve()
    artifacts_root = artifacts_root.resolve()
    mode = str(getattr(policy, "self_backup_mode", "initial_self_patch")).strip()
    workspace_repo_dir = _workspace_repo_dir(
        workspaces_dir=workspaces_dir,
        issue_id=issue_id,
        issue_dir_template=issue_dir_template,
        repo_dir_name=repo_dir_name,
    )
    self_target = runner_root == live_target_root

    logger.section("INITIAL SELF BACKUP")
    logger.line(f"self_backup_self_target={self_target}")
    logger.line(f"self_backup_mode={mode}")
    logger.line(f"self_backup_workspace_repo_dir={workspace_repo_dir}")

    if bool(getattr(policy, "test_mode", False)):
        logger.line("self_backup_skip_reason=test_mode")
        logger.info_core("self_backup=SKIP reason=test_mode")
        return InitialSelfBackupResult(
            created=False,
            skip_reason="test_mode",
            zip_path=None,
            archived_files=(),
            self_target=self_target,
        )
    if mode == "never":
        logger.line("self_backup_skip_reason=mode_never")
        logger.info_core("self_backup=SKIP reason=mode_never")
        return InitialSelfBackupResult(
            created=False,
            skip_reason="mode_never",
            zip_path=None,
            archived_files=(),
            self_target=self_target,
        )
    if not self_target:
        logger.line("self_backup_skip_reason=not_self_target")
        logger.info_core("self_backup=SKIP reason=not_self_target")
        return InitialSelfBackupResult(
            created=False,
            skip_reason="not_self_target",
            zip_path=None,
            archived_files=(),
            self_target=self_target,
        )
    if workspace_repo_dir.exists():
        logger.line("self_backup_skip_reason=workspace_exists")
        logger.info_core("self_backup=SKIP reason=workspace_exists")
        return InitialSelfBackupResult(
            created=False,
            skip_reason="workspace_exists",
            zip_path=None,
            archived_files=(),
            self_target=self_target,
        )

    include_relpaths = [
        str(item).strip()
        for item in list(getattr(policy, "self_backup_include_relpaths", []) or [])
        if str(item).strip()
    ]
    logger.line(f"self_backup_include_relpaths={include_relpaths!r}")
    archived_files = _resolve_archived_files(
        logger=logger,
        runner_root=runner_root,
        include_relpaths=include_relpaths,
    )
    zip_name = _render_backup_name(policy=policy, issue_id=issue_id)
    zip_path = _write_backup_zip(
        artifacts_root=artifacts_root,
        self_backup_dir=str(getattr(policy, "self_backup_dir", "quarantine")),
        zip_name=zip_name,
        runner_root=runner_root,
        archived_files=archived_files,
    )
    logger.line(f"self_backup_archived_file_count={len(archived_files)}")
    logger.line(f"self_backup_zip_path={zip_path}")
    logger.info_core(f"self_backup=CREATE path={zip_path}")
    return InitialSelfBackupResult(
        created=True,
        skip_reason=None,
        zip_path=zip_path,
        archived_files=archived_files,
        self_target=self_target,
    )
