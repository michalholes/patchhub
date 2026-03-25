from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _run(argv: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


class _RunResult:
    def __init__(self, stdout: str, stderr: str, returncode: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class _Logger:
    def run_logged(self, argv, *, cwd: Path, timeout_stage: str, env=None):
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
        )
        return _RunResult(result.stdout, result.stderr, result.returncode)


def _init_repo(repo: Path) -> None:
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test"], cwd=repo)


def _stage_and_commit_base(repo: Path) -> None:
    keep_path = repo / "keep.txt"
    keep_path.write_text("base\n", encoding="utf-8")
    _run(["git", "add", "keep.txt"], cwd=repo)
    _run(["git", "commit", "-m", "base"], cwd=repo)


repo_root = Path(__file__).resolve().parents[1]
scripts_dir = repo_root / "scripts"
sys.path.insert(0, str(scripts_dir))

from am_patch.errors import RunnerError  # noqa: E402
from am_patch.git_ops import commit  # noqa: E402


def test_commit_stage_all_ignores_am_patch_only_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    _stage_and_commit_base(repo)

    am_patch_dir = repo / ".am_patch"
    am_patch_dir.mkdir()
    (am_patch_dir / "tmp.txt").write_text("temp\n", encoding="utf-8")

    logger = _Logger()
    with pytest.raises(RunnerError, match="no changes to commit"):
        commit(logger, repo, "finalize")


def test_commit_stage_all_excludes_am_patch_from_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    _stage_and_commit_base(repo)

    keep_path = repo / "keep.txt"
    keep_path.write_text("changed\n", encoding="utf-8")

    am_patch_dir = repo / ".am_patch"
    am_patch_dir.mkdir()
    am_patch_file = am_patch_dir / "tmp.txt"
    am_patch_file.write_text("temp\n", encoding="utf-8")
    _run(["git", "add", ".am_patch/tmp.txt"], cwd=repo)

    logger = _Logger()
    commit_sha = commit(logger, repo, "finalize")

    names = _run(
        ["git", "show", "--name-only", "--pretty=format:", commit_sha],
        cwd=repo,
    )
    changed = {line.strip() for line in names.splitlines() if line.strip()}

    assert "keep.txt" in changed
    assert ".am_patch/tmp.txt" not in changed
    assert am_patch_file.exists()

    status = _run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo)
    assert ".am_patch/tmp.txt" in status
