import subprocess
from pathlib import Path

import pytest
from scripts.am_patch.errors import RunnerError
from scripts.am_patch.log import Logger
from scripts.am_patch.patch_exec import run_patch, run_unified_patch_bundle


class _Policy:
    patch_jail = True
    patch_jail_unshare_net = True
    ascii_only_patch = False
    unified_patch_strip = 1


def _new_logger(tmp_path: Path) -> Logger:
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return Logger(
        log_path=logs / "t.log",
        symlink_path=logs / "t.symlink",
        screen_level="quiet",
        log_level="debug",
        symlink_enabled=False,
    )


def _make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True)
    (repo / "README.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.txt"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )
    return repo


def test_run_patch_missing_bwrap_path_fails_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("AM_PATCH_BWRAP", raising=False)
    monkeypatch.setattr("scripts.am_patch.patch_exec.shutil.which", lambda _name: None)

    repo = _make_git_repo(tmp_path)
    patch_script = tmp_path / "p.py"
    patch_script.write_text("FILES=[]\n", encoding="utf-8")

    logger = _new_logger(tmp_path)
    with pytest.raises(RunnerError) as ei:
        run_patch(logger, patch_script, workspace_repo=repo, policy=_Policy())
    err = ei.value
    assert err.stage == "PREFLIGHT"
    assert err.category == "BWRAP"


def test_run_patch_invalid_env_path_fails_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AM_PATCH_BWRAP", "/does/not/exist")
    # Ensure PATH resolution would not find bwrap either.
    monkeypatch.setattr("scripts.am_patch.patch_exec.shutil.which", lambda _name: None)

    repo = _make_git_repo(tmp_path)
    patch_script = tmp_path / "p.py"
    patch_script.write_text("FILES=[]\n", encoding="utf-8")

    logger = _new_logger(tmp_path)
    with pytest.raises(RunnerError) as ei:
        run_patch(logger, patch_script, workspace_repo=repo, policy=_Policy())
    err = ei.value
    assert err.stage == "PREFLIGHT"
    assert err.category == "BWRAP"


def test_run_patch_invalid_env_name_fails_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AM_PATCH_BWRAP", "bwrap-does-not-exist")
    monkeypatch.setattr("scripts.am_patch.patch_exec.shutil.which", lambda _name: None)

    repo = _make_git_repo(tmp_path)
    patch_script = tmp_path / "p.py"
    patch_script.write_text("FILES=[]\n", encoding="utf-8")

    logger = _new_logger(tmp_path)
    with pytest.raises(RunnerError) as ei:
        run_patch(logger, patch_script, workspace_repo=repo, policy=_Policy())
    err = ei.value
    assert err.stage == "PREFLIGHT"
    assert err.category == "BWRAP"


def test_unified_patch_path_missing_bwrap_fails_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("AM_PATCH_BWRAP", raising=False)
    monkeypatch.setattr("scripts.am_patch.patch_exec.shutil.which", lambda _name: None)

    repo = _make_git_repo(tmp_path)

    patch_text = "\n".join(
        [
            "diff --git a/x.txt b/x.txt",
            "new file mode 100644",
            "index 0000000..e69de29",
            "--- /dev/null",
            "+++ b/x.txt",
            "@@ -0,0 +1 @@",
            "+x",
            "",
        ]
    )
    patch_path = tmp_path / "u.patch"
    patch_path.write_text(patch_text, encoding="utf-8")

    logger = _new_logger(tmp_path)
    with pytest.raises(RunnerError) as ei:
        run_unified_patch_bundle(logger, patch_path, workspace_repo=repo, policy=_Policy())
    err = ei.value
    assert err.stage == "PREFLIGHT"
    assert err.category == "BWRAP"
