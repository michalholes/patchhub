from __future__ import annotations

import subprocess
from pathlib import Path

from badguys.bdg_evaluator import StepResult


def _workspace_repo_root(*, repo_root: Path, issue_id: str) -> Path:
    return repo_root / "patches" / "workspaces" / f"issue_{issue_id}" / "repo"


def execute_git_status_porcelain(
    *,
    repo_root: Path,
    issue_id: str,
    scope: str,
) -> StepResult:
    if scope not in {"root", "workspace"}:
        raise SystemExit("FAIL: bdg: scope must be 'root' or 'workspace'")
    cwd = repo_root
    if scope == "workspace":
        cwd = _workspace_repo_root(repo_root=repo_root, issue_id=issue_id)
        if not cwd.exists():
            return StepResult(
                rc=1,
                stdout=None,
                stderr=f"missing workspace repo: {cwd}",
                value=[],
            )
    cp = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if cp.returncode != 0:
        return StepResult(rc=1, stdout=None, stderr=(cp.stderr or "git status failed"), value=[])
    lines = (cp.stdout or "").splitlines()
    out = [ln.rstrip("\n") for ln in lines if ln.strip()]
    return StepResult(rc=0, stdout=None, stderr=None, value=out)
