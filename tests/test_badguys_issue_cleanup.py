from __future__ import annotations

from pathlib import Path

from badguys.run_suite import Ctx, SuiteCfg, _cleanup_issue_artifacts

ISSUE_ID = "666"
OTHER_ISSUE_ID = "777"


def _make_ctx(repo_root: Path) -> Ctx:
    patches_dir = repo_root / "patches"
    central_log = patches_dir / "badguys_test.log"
    cfg = SuiteCfg(
        repo_root=repo_root,
        config_path="badguys/config.toml",
        issue_id=ISSUE_ID,
        runner_cmd=[
            "python3",
            "scripts/am_patch.py",
            "--ipc-socket-mode=patch_dir",
            "--ipc-socket-name-template=am_patch_ipc_{issue}.sock",
        ],
        patches_dir=patches_dir,
        logs_dir=patches_dir / "badguys_logs",
        central_log_pattern="patches/badguys_{run_id}.log",
        lock_path=patches_dir / "badguys.lock",
        lock_ttl_seconds=3600,
        lock_on_conflict="fail",
        console_verbosity="quiet",
        log_verbosity="quiet",
        per_run_logs_post_run="keep_all",
        full_runner_tests=[],
        copy_runner_log=False,
        write_subprocess_stdio=False,
        suite_jail=False,
    )
    return Ctx(
        repo_root=repo_root,
        run_id="testrun",
        central_log=central_log,
        cfg=cfg,
        console_verbosity="quiet",
        log_verbosity="quiet",
    )


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def test_cleanup_issue_artifacts_removes_current_artifacts_each_time(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path)
    patches_dir = ctx.cfg.patches_dir

    def seed_current_issue() -> None:
        _touch(patches_dir / f"am_patch_ipc_{ISSUE_ID}.sock")
        _touch(patches_dir / "logs" / f"issue_{ISSUE_ID}_runner.log")
        _touch(patches_dir / "successful" / f"issue_{ISSUE_ID}_success.zip")
        _touch(patches_dir / "unsuccessful" / f"issue_{ISSUE_ID}_failure.zip")
        _touch(patches_dir / f"patched_issue{ISSUE_ID}_v01.zip")
        _touch(patches_dir / f"issue_{ISSUE_ID}__bdg__test_probe.json")
        _touch(
            patches_dir / "badguys_artifacts" / f"issue_{ISSUE_ID}" / "test_probe" / "artifact.txt"
        )
        _touch(
            patches_dir
            / "workspaces"
            / f"issue_{ISSUE_ID}"
            / "repo"
            / "scripts"
            / "badguys_batch3"
            / "marker.txt"
        )

    seed_current_issue()
    _cleanup_issue_artifacts(ctx, issue_id=ISSUE_ID, test_id="test_probe")

    assert not (patches_dir / f"am_patch_ipc_{ISSUE_ID}.sock").exists()
    assert not (patches_dir / "logs" / f"issue_{ISSUE_ID}_runner.log").exists()
    assert not (patches_dir / "successful" / f"issue_{ISSUE_ID}_success.zip").exists()
    assert not (patches_dir / "unsuccessful" / f"issue_{ISSUE_ID}_failure.zip").exists()
    assert not (patches_dir / f"patched_issue{ISSUE_ID}_v01.zip").exists()
    assert not (patches_dir / f"issue_{ISSUE_ID}__bdg__test_probe.json").exists()
    assert not (patches_dir / "badguys_artifacts" / f"issue_{ISSUE_ID}").exists()
    assert not (patches_dir / "workspaces" / f"issue_{ISSUE_ID}").exists()

    seed_current_issue()
    _cleanup_issue_artifacts(ctx, issue_id=ISSUE_ID, test_id="test_probe")

    assert not (patches_dir / f"am_patch_ipc_{ISSUE_ID}.sock").exists()
    assert not (patches_dir / "workspaces" / f"issue_{ISSUE_ID}").exists()


def test_cleanup_issue_artifacts_preserves_other_issue_artifacts(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path)
    patches_dir = ctx.cfg.patches_dir

    _touch(patches_dir / f"am_patch_ipc_{ISSUE_ID}.sock")
    _touch(patches_dir / f"am_patch_ipc_{OTHER_ISSUE_ID}.sock")
    _touch(patches_dir / "logs" / f"issue_{OTHER_ISSUE_ID}_runner.log")
    _touch(patches_dir / "successful" / f"issue_{OTHER_ISSUE_ID}_success.zip")
    _touch(patches_dir / "unsuccessful" / f"issue_{OTHER_ISSUE_ID}_failure.zip")
    _touch(patches_dir / f"patched_issue{OTHER_ISSUE_ID}_v01.zip")
    _touch(patches_dir / f"issue_{OTHER_ISSUE_ID}__bdg__test_probe.json")
    _touch(
        patches_dir
        / "badguys_artifacts"
        / f"issue_{OTHER_ISSUE_ID}"
        / "test_probe"
        / "artifact.txt"
    )
    _touch(
        patches_dir
        / "workspaces"
        / f"issue_{OTHER_ISSUE_ID}"
        / "repo"
        / "scripts"
        / "badguys_batch3"
        / "marker.txt"
    )

    _cleanup_issue_artifacts(ctx, issue_id=ISSUE_ID, test_id="test_probe")

    assert not (patches_dir / f"am_patch_ipc_{ISSUE_ID}.sock").exists()
    assert (patches_dir / f"am_patch_ipc_{OTHER_ISSUE_ID}.sock").exists()
    assert (patches_dir / "logs" / f"issue_{OTHER_ISSUE_ID}_runner.log").exists()
    assert (patches_dir / "successful" / f"issue_{OTHER_ISSUE_ID}_success.zip").exists()
    assert (patches_dir / "unsuccessful" / f"issue_{OTHER_ISSUE_ID}_failure.zip").exists()
    assert (patches_dir / f"patched_issue{OTHER_ISSUE_ID}_v01.zip").exists()
    assert (patches_dir / f"issue_{OTHER_ISSUE_ID}__bdg__test_probe.json").exists()
    assert (patches_dir / "badguys_artifacts" / f"issue_{OTHER_ISSUE_ID}").exists()
    assert (patches_dir / "workspaces" / f"issue_{OTHER_ISSUE_ID}").exists()
