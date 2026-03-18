from __future__ import annotations

import tomllib
import zipfile
from pathlib import Path
from typing import Any

from badguys.bdg_evaluator import StepResult


def logs_dir(*, repo_root: Path, config_path: Path) -> Path:
    cfg_path = repo_root / config_path
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    logs_rel = raw.get("suite", {}).get("logs_dir", "patches/badguys_logs")
    return repo_root / Path(str(logs_rel))


def _workspace_repo_root(*, repo_root: Path, issue_id: str) -> Path:
    return repo_root / "patches" / "workspaces" / f"issue_{issue_id}" / "repo"


def _expand_relpath_vars(*, relpath: str, repo_root: Path, issue_id: str) -> str:
    out = str(relpath)
    out = out.replace("${issue_id}", str(issue_id))
    out = out.replace("${repo_name}", repo_root.name)
    return out


def _normalize_relpath(*, relpath: str, label: str) -> Path:
    if not relpath.strip():
        raise SystemExit(f"FAIL: bdg: {label} must be non-empty")
    path = Path(relpath)
    if path.is_absolute():
        raise SystemExit(f"FAIL: bdg: {label} must be repo-relative")
    if any(part == ".." for part in path.parts):
        raise SystemExit(f"FAIL: bdg: {label} must not contain '..'")
    return path


def _resolve_scope_root(
    *,
    repo_root: Path,
    issue_id: str,
    artifacts_dir: Path,
    scope: str,
) -> tuple[Path | None, str | None]:
    if scope == "repo":
        return repo_root, None
    if scope == "artifacts":
        return artifacts_dir, None
    if scope == "workspace":
        ws_root = _workspace_repo_root(repo_root=repo_root, issue_id=issue_id)
        if not ws_root.exists():
            return None, f"missing workspace repo: {ws_root}"
        return ws_root, None
    raise SystemExit("FAIL: bdg: scope must be repo|artifacts|workspace")


def _resolve_step_path(
    *,
    repo_root: Path,
    step: dict[str, Any],
    artifacts_dir: Path,
    issue_id: str,
) -> tuple[Path | None, str | None]:
    scope = step.get("scope", "repo")
    relpath = step.get("relpath")
    if not isinstance(scope, str):
        raise SystemExit("FAIL: bdg: scope must be string")
    if not isinstance(relpath, str):
        raise SystemExit("FAIL: bdg: relpath must be string")
    root, err = _resolve_scope_root(
        repo_root=repo_root,
        issue_id=issue_id,
        artifacts_dir=artifacts_dir,
        scope=scope,
    )
    if root is None:
        return None, err
    path = root / _normalize_relpath(
        relpath=_expand_relpath_vars(relpath=relpath, repo_root=repo_root, issue_id=issue_id),
        label="relpath",
    )
    return path, None


def execute_read_text_file(
    *,
    repo_root: Path,
    step: dict[str, Any],
    artifacts_dir: Path,
    issue_id: str,
) -> StepResult:
    path, err = _resolve_step_path(
        repo_root=repo_root,
        step=step,
        artifacts_dir=artifacts_dir,
        issue_id=issue_id,
    )
    if path is None:
        return StepResult(rc=1, stdout=None, stderr=err, value="")
    if not path.exists():
        return StepResult(rc=1, stdout=None, stderr=f"missing file: {path}", value="")
    return StepResult(
        rc=0,
        stdout=None,
        stderr=None,
        value=path.read_text(encoding="utf-8"),
    )


def execute_zip_list(
    *,
    repo_root: Path,
    step: dict[str, Any],
    artifacts_dir: Path,
    issue_id: str,
) -> StepResult:
    path, err = _resolve_step_path(
        repo_root=repo_root,
        step=step,
        artifacts_dir=artifacts_dir,
        issue_id=issue_id,
    )
    if path is None:
        return StepResult(rc=1, stdout=None, stderr=err, value=[])
    if not path.exists():
        return StepResult(rc=1, stdout=None, stderr=f"missing file: {path}", value=[])
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = sorted(info.filename for info in zf.infolist())
    except zipfile.BadZipFile:
        return StepResult(rc=1, stdout=None, stderr=f"invalid zip: {path}", value=[])
    return StepResult(rc=0, stdout=None, stderr=None, value=names)


def execute_read_step_log(
    *,
    repo_root: Path,
    config_path: Path,
    test_name: str,
) -> StepResult:
    log_dir = logs_dir(repo_root=repo_root, config_path=config_path)
    log_path = log_dir / test_name / "badguys.test.jsonl"
    if not log_path.exists():
        return StepResult(rc=1, stdout=None, stderr=f"missing log: {log_path}", value="")
    return StepResult(
        rc=0,
        stdout=None,
        stderr=None,
        value=log_path.read_text(encoding="utf-8"),
    )
