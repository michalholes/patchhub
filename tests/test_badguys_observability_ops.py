from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest
from badguys.bdg_executor import execute_bdg_step
from badguys.bdg_loader import BdgStep
from badguys.bdg_materializer import MaterializedAssets
from badguys.bdg_subst import SubstCtx


def _write_config(repo_root: Path) -> Path:
    cfg_path = repo_root / "badguys" / "config_ops.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        """
[suite]
issue_id = "777"
runner_cmd = ["python3", "scripts/am_patch.py"]
runner_verbosity = "quiet"
console_verbosity = "quiet"
log_verbosity = "quiet"
patches_dir = "patches"
logs_dir = "patches/badguys_logs"
commit_limit = 0

[lock]
path = "patches/badguys.lock"
ttl_seconds = 3600
on_conflict = "fail"

[guard]
require_guard_test = false
guard_test_name = "test_000_test_mode_smoke"
abort_on_guard_fail = true

[filters]
include = []
exclude = []

[runner]
full_runner_tests = []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return cfg_path


def _step_runner_cfg(repo_root: Path, *, artifacts_dir: Path) -> dict[str, object]:
    return {
        "artifacts_dir": artifacts_dir,
        "console_verbosity": "quiet",
        "copy_runner_log": False,
        "patches_dir": repo_root / "patches",
        "write_subprocess_stdio": False,
    }


def _mats(repo_root: Path) -> MaterializedAssets:
    return MaterializedAssets(
        root=repo_root / "patches" / "mats",
        files={},
        subjects={
            "delete_marker": "docs/delete_me.txt",
            "delete_dir": "docs/delete_dir",
        },
    )


def test_read_text_file_and_zip_list_use_step_scopes(tmp_path: Path) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root)
    (repo_root / "docs").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "repo_note.txt").write_text("repo text\n", encoding="utf-8")

    artifacts_dir = repo_root / "patches" / "badguys_logs" / "test_ops"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = artifacts_dir / "bundle.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("b/file.txt", "b")
        zf.writestr("a/file.txt", "a")

    subst = SubstCtx(issue_id="777", now_stamp="20260308_090000")
    mats = _mats(repo_root)

    read_result = execute_bdg_step(
        repo_root=repo_root,
        config_path=cfg_path.relative_to(repo_root),
        cfg_runner_cmd=["python3", "scripts/am_patch.py"],
        subst=subst,
        full_runner_tests=set(),
        step=BdgStep(
            op="READ_TEXT_FILE",
            params={"scope": "repo", "relpath": "docs/repo_note.txt"},
        ),
        mats=mats,
        test_id="test_ops",
        step_index=0,
        step_runner_cfg=_step_runner_cfg(repo_root, artifacts_dir=artifacts_dir),
    )
    zip_result = execute_bdg_step(
        repo_root=repo_root,
        config_path=cfg_path.relative_to(repo_root),
        cfg_runner_cmd=["python3", "scripts/am_patch.py"],
        subst=subst,
        full_runner_tests=set(),
        step=BdgStep(op="ZIP_LIST", params={"scope": "artifacts", "relpath": "bundle.zip"}),
        mats=mats,
        test_id="test_ops",
        step_index=1,
        step_runner_cfg=_step_runner_cfg(repo_root, artifacts_dir=artifacts_dir),
    )

    assert read_result.rc == 0
    assert read_result.value == "repo text\n"
    assert zip_result.rc == 0
    assert zip_result.value == ["a/file.txt", "b/file.txt"]


def test_read_text_file_workspace_scope_reads_workspace_repo(tmp_path: Path) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root)
    ws_file = (
        repo_root / "patches" / "workspaces" / "issue_777" / "repo" / "docs" / "workspace_note.txt"
    )
    ws_file.parent.mkdir(parents=True, exist_ok=True)
    ws_file.write_text("workspace text\n", encoding="utf-8")

    result = execute_bdg_step(
        repo_root=repo_root,
        config_path=cfg_path.relative_to(repo_root),
        cfg_runner_cmd=["python3", "scripts/am_patch.py"],
        subst=SubstCtx(issue_id="777", now_stamp="20260308_090000"),
        full_runner_tests=set(),
        step=BdgStep(
            op="READ_TEXT_FILE",
            params={"scope": "workspace", "relpath": "docs/workspace_note.txt"},
        ),
        mats=_mats(repo_root),
        test_id="test_ops",
        step_index=2,
        step_runner_cfg=_step_runner_cfg(
            repo_root,
            artifacts_dir=repo_root / "patches" / "badguys_logs" / "test_ops",
        ),
    )

    assert result.rc == 0
    assert result.value == "workspace text\n"


def test_git_status_porcelain_supports_workspace_scope(tmp_path: Path) -> None:
    repo_root = tmp_path
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    ws_repo = repo_root / "patches" / "workspaces" / "issue_777" / "repo"
    ws_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=ws_repo, check=True, capture_output=True, text=True)
    dirty = ws_repo / "dirty.txt"
    dirty.write_text("dirty\n", encoding="utf-8")

    result = execute_bdg_step(
        repo_root=repo_root,
        config_path=Path("badguys/config.toml"),
        cfg_runner_cmd=["python3", "scripts/am_patch.py"],
        subst=SubstCtx(issue_id="777", now_stamp="20260308_090000"),
        full_runner_tests=set(),
        step=BdgStep(op="GIT_STATUS_PORCELAIN", params={"scope": "workspace"}),
        mats=_mats(repo_root),
        test_id="test_ops",
        step_index=0,
        step_runner_cfg=_step_runner_cfg(
            repo_root,
            artifacts_dir=repo_root / "patches" / "badguys_logs" / "test_ops",
        ),
    )

    assert result.rc == 0
    assert result.value == ["?? dirty.txt"]


def test_delete_subject_removes_existing_file_subject(tmp_path: Path) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root)
    target = repo_root / "patches" / "workspaces" / "issue_777" / "repo" / "docs" / "delete_me.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("delete me\n", encoding="utf-8")

    result = execute_bdg_step(
        repo_root=repo_root,
        config_path=cfg_path.relative_to(repo_root),
        cfg_runner_cmd=["python3", "scripts/am_patch.py"],
        subst=SubstCtx(issue_id="777", now_stamp="20260308_090000"),
        full_runner_tests=set(),
        step=BdgStep(op="DELETE_SUBJECT", params={"subject": "delete_marker"}),
        mats=_mats(repo_root),
        test_id="test_ops",
        step_index=3,
        step_runner_cfg=_step_runner_cfg(
            repo_root,
            artifacts_dir=repo_root / "patches" / "badguys_logs" / "test_ops",
        ),
    )

    assert result.rc == 0
    assert result.value == str(target)
    assert not target.exists()


def test_delete_subject_is_idempotent_when_file_missing(tmp_path: Path) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root)
    target = repo_root / "patches" / "workspaces" / "issue_777" / "repo" / "docs" / "delete_me.txt"
    target.parent.mkdir(parents=True, exist_ok=True)

    result = execute_bdg_step(
        repo_root=repo_root,
        config_path=cfg_path.relative_to(repo_root),
        cfg_runner_cmd=["python3", "scripts/am_patch.py"],
        subst=SubstCtx(issue_id="777", now_stamp="20260308_090000"),
        full_runner_tests=set(),
        step=BdgStep(op="DELETE_SUBJECT", params={"subject": "delete_marker"}),
        mats=_mats(repo_root),
        test_id="test_ops",
        step_index=4,
        step_runner_cfg=_step_runner_cfg(
            repo_root,
            artifacts_dir=repo_root / "patches" / "badguys_logs" / "test_ops",
        ),
    )

    assert result.rc == 0
    assert result.value == str(target)
    assert not target.exists()


def test_delete_subject_fails_for_unknown_subject(tmp_path: Path) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root)

    with pytest.raises(SystemExit, match="unknown subject 'missing_subject'"):
        execute_bdg_step(
            repo_root=repo_root,
            config_path=cfg_path.relative_to(repo_root),
            cfg_runner_cmd=["python3", "scripts/am_patch.py"],
            subst=SubstCtx(issue_id="777", now_stamp="20260308_090000"),
            full_runner_tests=set(),
            step=BdgStep(op="DELETE_SUBJECT", params={"subject": "missing_subject"}),
            mats=_mats(repo_root),
            test_id="test_ops",
            step_index=5,
            step_runner_cfg=_step_runner_cfg(
                repo_root,
                artifacts_dir=repo_root / "patches" / "badguys_logs" / "test_ops",
            ),
        )


def test_delete_subject_fails_for_directory_target(tmp_path: Path) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root)
    target = repo_root / "patches" / "workspaces" / "issue_777" / "repo" / "docs" / "delete_dir"
    target.mkdir(parents=True, exist_ok=True)

    result = execute_bdg_step(
        repo_root=repo_root,
        config_path=cfg_path.relative_to(repo_root),
        cfg_runner_cmd=["python3", "scripts/am_patch.py"],
        subst=SubstCtx(issue_id="777", now_stamp="20260308_090000"),
        full_runner_tests=set(),
        step=BdgStep(op="DELETE_SUBJECT", params={"subject": "delete_dir"}),
        mats=_mats(repo_root),
        test_id="test_ops",
        step_index=6,
        step_runner_cfg=_step_runner_cfg(
            repo_root,
            artifacts_dir=repo_root / "patches" / "badguys_logs" / "test_ops",
        ),
    )

    assert result.rc == 1
    assert result.stderr == "DELETE_SUBJECT target is directory"
    assert result.value == str(target)
    assert target.exists()
