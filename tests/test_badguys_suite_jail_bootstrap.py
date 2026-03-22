from __future__ import annotations

import subprocess
from pathlib import Path

from badguys.bdg_suite_jail import prepare_suite_jail, teardown_suite_jail

ISSUE_ID = "662"


def _git(repo_root: Path, *argv: str) -> str:
    proc = subprocess.run(
        ["git", *argv],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_repo(repo_root: Path) -> None:
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    _write(repo_root / "tracked.txt", "tracked\n")
    _git(repo_root, "add", "tracked.txt")
    _git(repo_root, "commit", "-m", "base")


def test_prepare_suite_jail_bootstraps_git_repo_without_runtime_baggage(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    _init_repo(repo_root)

    quarantine_marker = repo_root / "quarantine" / "marker.txt"
    issue_patch = repo_root / "patches" / f"issue_{ISSUE_ID}__bdg__sample.patch"
    issue_artifact = (
        repo_root / "patches" / "badguys_artifacts" / f"issue_{ISSUE_ID}" / "artifact.txt"
    )
    logs_dir = repo_root / "patches" / "badguys_logs"
    central_log = repo_root / "patches" / "badguys_testrun.log"

    logs_dir.mkdir(parents=True, exist_ok=True)
    _write(quarantine_marker, "host quarantine baggage\n")
    _write(issue_patch, "host patch baggage\n")
    _write(issue_artifact, "host artifact baggage\n")

    jail = prepare_suite_jail(
        host_repo_root=repo_root,
        issue_id=ISSUE_ID,
        host_bind_paths=[logs_dir, central_log],
    )
    try:
        expected_root = repo_root / "patches" / "badguys_suite_jail" / f"issue_{ISSUE_ID}"
        assert jail.root == expected_root
        assert jail.repo_root == expected_root / "repo"
        assert jail.repo_root.is_dir()
        assert (jail.repo_root / ".git").is_dir()
        assert (jail.repo_root / "tracked.txt").read_text(encoding="utf-8") == "tracked\n"

        assert not (jail.repo_root / "quarantine").exists()
        assert not (jail.repo_root / "patches" / issue_patch.name).exists()
        assert not (jail.repo_root / issue_artifact.relative_to(repo_root)).exists()

        assert (jail.repo_root / logs_dir.relative_to(repo_root)).is_dir()
        assert (jail.repo_root / central_log.relative_to(repo_root)).is_file()

        created_patches_entries = sorted(
            path.relative_to(jail.repo_root / "patches").as_posix()
            for path in (jail.repo_root / "patches").rglob("*")
        )
        assert created_patches_entries == [
            "badguys_logs",
            "badguys_testrun.log",
        ]
    finally:
        teardown_suite_jail(repo_root, ISSUE_ID)

    assert not (repo_root / "patches" / "badguys_suite_jail" / f"issue_{ISSUE_ID}").exists()
    assert quarantine_marker.exists()
    assert issue_patch.exists()
    assert issue_artifact.exists()
