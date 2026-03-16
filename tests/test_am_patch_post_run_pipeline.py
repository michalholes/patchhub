from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class _FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.sections: list[str] = []

    def section(self, name: str) -> None:
        self.sections.append(name)

    def line(self, text: str) -> None:
        self.lines.append(text)


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "amp"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.errors import RunnerError
    from am_patch.post_run_pipeline import run_post_run_pipeline
    from am_patch.run_result import build_run_result

    return RunnerError, build_run_result, run_post_run_pipeline


def _ctx(tmp_path: Path, *, mode: str, logger: _FakeLogger) -> Any:
    paths = SimpleNamespace(
        patch_dir=tmp_path / "patches",
        successful_dir=tmp_path / "patches" / "successful",
        unsuccessful_dir=tmp_path / "patches" / "unsuccessful",
        workspaces_dir=tmp_path / "patches" / "workspaces",
        logs_dir=tmp_path / "patches" / "logs",
        artifacts_dir=tmp_path / "patches" / "artifacts",
    )
    for path in (
        paths.patch_dir,
        paths.successful_dir,
        paths.unsuccessful_dir,
        paths.workspaces_dir,
        paths.logs_dir,
        paths.artifacts_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    policy = SimpleNamespace(
        test_mode=False,
        rollback_workspace_on_fail="none-applied",
        post_success_audit=True,
    )
    cli = SimpleNamespace(mode=mode, issue_id="999", patch_script=None)
    return SimpleNamespace(
        cli=cli,
        policy=policy,
        repo_root=tmp_path / "repo",
        paths=paths,
        log_path=paths.logs_dir / "run.log",
        logger=logger,
    )


def _success_result(build_run_result, *, tmp_path: Path) -> Any:
    ws_root = tmp_path / "patches" / "workspaces" / "issue_999"
    ws_repo = ws_root / "repo"
    ws_repo.mkdir(parents=True, exist_ok=True)
    used_patch = tmp_path / "patches" / "successful" / "issue_999.py"
    used_patch.write_text("x", encoding="utf-8")
    return build_run_result(
        lock=None,
        exit_code=0,
        unified_mode=False,
        patch_script=None,
        used_patch_for_zip=used_patch,
        files_for_fail_zip=[],
        failed_patch_blobs_for_zip=[],
        patch_applied_successfully=True,
        applied_ok_count=1,
        rollback_ckpt_for_posthook=None,
        rollback_ws_for_posthook=None,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["amp/am_patch/engine.py"],
        delete_workspace_after_archive=True,
        ws_for_posthook=SimpleNamespace(root=ws_root, repo=ws_repo, attempt=2),
        push_ok_for_posthook=True,
        final_commit_sha="deadbeef",
        final_pushed_files=["M amp/am_patch/engine.py"],
        final_fail_stage=None,
        final_fail_reason=None,
        primary_fail_stage=None,
        primary_fail_reason=None,
        secondary_failures=[],
    )


def test_workspace_audit_runs_once_after_workspace_delete(tmp_path: Path) -> None:
    _, build_run_result, post_run_pipeline = _import_am_patch()
    logger = _FakeLogger()
    ctx = _ctx(tmp_path, mode="workspace", logger=logger)
    ctx.repo_root.mkdir(parents=True, exist_ok=True)
    result = _success_result(build_run_result, tmp_path=tmp_path)

    post_run_mod = sys.modules[post_run_pipeline.__module__]
    events: list[str] = []

    post_run_mod.delete_workspace = lambda logger, ws: events.append("delete")
    post_run_mod.run_post_success_audit = lambda logger, repo_root, policy: events.append("audit")

    def _build_artifacts(**kwargs):
        events.append("artifacts")
        assert kwargs["ws_repo_for_fail_zip"] == ctx.repo_root

    post_run_mod.build_artifacts = _build_artifacts

    exit_code = post_run_pipeline(ctx=ctx, result=result)

    assert exit_code == 0
    assert events == ["delete", "audit", "artifacts"]


def test_audit_failure_switches_result_to_fail(tmp_path: Path) -> None:
    runner_error_cls, build_run_result, post_run_pipeline = _import_am_patch()
    logger = _FakeLogger()
    ctx = _ctx(tmp_path, mode="finalize", logger=logger)
    ctx.repo_root.mkdir(parents=True, exist_ok=True)
    result = build_run_result(
        lock=None,
        exit_code=0,
        unified_mode=False,
        patch_script=None,
        used_patch_for_zip=None,
        files_for_fail_zip=[],
        failed_patch_blobs_for_zip=[],
        patch_applied_successfully=True,
        applied_ok_count=1,
        rollback_ckpt_for_posthook=None,
        rollback_ws_for_posthook=None,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["amp/am_patch/engine.py"],
        delete_workspace_after_archive=False,
        ws_for_posthook=None,
        push_ok_for_posthook=True,
        final_commit_sha="deadbeef",
        final_pushed_files=None,
        final_fail_stage=None,
        final_fail_reason=None,
        primary_fail_stage=None,
        primary_fail_reason=None,
        secondary_failures=[],
    )

    post_run_mod = sys.modules[post_run_pipeline.__module__]
    post_run_mod.changed_paths = lambda logger, repo_root: []
    post_run_mod.run_post_success_audit = lambda logger, repo_root, policy: (_ for _ in ()).throw(
        runner_error_cls("AUDIT", "AUDIT_REPORT_FAILED", "audit/audit_report.py failed")
    )

    captured: dict[str, Any] = {}

    def _build_artifacts(**kwargs):
        captured.update(kwargs)

    post_run_mod.build_artifacts = _build_artifacts

    exit_code = post_run_pipeline(ctx=ctx, result=result)

    assert exit_code == 1
    assert result.final_fail_stage == "AUDIT"
    assert result.final_fail_reason == "audit failed"
    assert captured["exit_code"] == 1


def test_finalize_failure_uses_live_repo_union_for_failure_zip(tmp_path: Path) -> None:
    _, build_run_result, post_run_pipeline = _import_am_patch()
    logger = _FakeLogger()
    ctx = _ctx(tmp_path, mode="finalize", logger=logger)
    ctx.repo_root.mkdir(parents=True, exist_ok=True)
    result = build_run_result(
        lock=None,
        exit_code=1,
        unified_mode=False,
        patch_script=None,
        used_patch_for_zip=None,
        files_for_fail_zip=["carry.py"],
        failed_patch_blobs_for_zip=[],
        patch_applied_successfully=True,
        applied_ok_count=1,
        rollback_ckpt_for_posthook=None,
        rollback_ws_for_posthook=None,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["alpha.py", "beta.py"],
        delete_workspace_after_archive=False,
        ws_for_posthook=None,
        push_ok_for_posthook=False,
        final_commit_sha=None,
        final_pushed_files=None,
        final_fail_stage="RUFF",
        final_fail_reason="gate failed",
        primary_fail_stage="RUFF",
        primary_fail_reason="gate failed",
        secondary_failures=[],
    )

    post_run_mod = sys.modules[post_run_pipeline.__module__]
    post_run_mod.changed_paths = lambda logger, repo_root: ["beta.py", "gamma.py"]

    captured: dict[str, Any] = {}

    def _build_artifacts(**kwargs):
        captured.update(kwargs)

    post_run_mod.build_artifacts = _build_artifacts

    exit_code = post_run_pipeline(ctx=ctx, result=result)

    assert exit_code == 1
    assert captured["ws_repo_for_fail_zip"] == ctx.repo_root
    assert captured["files_for_fail_zip"] == [
        "alpha.py",
        "beta.py",
        "carry.py",
        "gamma.py",
    ]


def test_gate_failure_skips_workspace_rollback_when_mode_is_always(tmp_path: Path) -> None:
    _, build_run_result, post_run_pipeline = _import_am_patch()
    logger = _FakeLogger()
    ctx = _ctx(tmp_path, mode="workspace", logger=logger)
    ctx.repo_root.mkdir(parents=True, exist_ok=True)
    ctx.policy.rollback_workspace_on_fail = "always"

    ws_root = tmp_path / "patches" / "workspaces" / "issue_999"
    ws_repo = ws_root / "repo"
    ws_repo.mkdir(parents=True, exist_ok=True)
    ws = SimpleNamespace(root=ws_root, repo=ws_repo, attempt=1)
    ckpt = object()
    result = build_run_result(
        lock=None,
        exit_code=1,
        unified_mode=False,
        patch_script=None,
        used_patch_for_zip=None,
        files_for_fail_zip=["alpha.py"],
        failed_patch_blobs_for_zip=[],
        patch_applied_successfully=True,
        applied_ok_count=1,
        rollback_ckpt_for_posthook=ckpt,
        rollback_ws_for_posthook=ws,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["alpha.py"],
        delete_workspace_after_archive=False,
        ws_for_posthook=ws,
        push_ok_for_posthook=False,
        final_commit_sha=None,
        final_pushed_files=None,
        final_fail_stage="GATE_PYTEST",
        final_fail_reason="gates failed",
        primary_fail_stage="GATES",
        primary_fail_reason="gate failed",
        secondary_failures=[],
    )

    post_run_mod = sys.modules[post_run_pipeline.__module__]
    rollback_calls: list[tuple[Path, object]] = []
    post_run_mod.build_artifacts = lambda **kwargs: None
    post_run_mod.rollback_to_checkpoint = lambda logger, repo, checkpoint: rollback_calls.append(
        (repo, checkpoint)
    )

    exit_code = post_run_pipeline(ctx=ctx, result=result)

    assert exit_code == 1
    assert rollback_calls == []
    assert (
        logger.lines.count("ROLLBACK: skipped (mode=always reason=non-patch-failure applied_ok=1)")
        == 1
    )


def test_patch_failure_rolls_back_workspace_when_mode_is_always(tmp_path: Path) -> None:
    _, build_run_result, post_run_pipeline = _import_am_patch()
    logger = _FakeLogger()
    ctx = _ctx(tmp_path, mode="workspace", logger=logger)
    ctx.repo_root.mkdir(parents=True, exist_ok=True)
    ctx.policy.rollback_workspace_on_fail = "always"

    ws_root = tmp_path / "patches" / "workspaces" / "issue_999"
    ws_repo = ws_root / "repo"
    ws_repo.mkdir(parents=True, exist_ok=True)
    ws = SimpleNamespace(root=ws_root, repo=ws_repo, attempt=1)
    ckpt = object()
    result = build_run_result(
        lock=None,
        exit_code=1,
        unified_mode=False,
        patch_script=None,
        used_patch_for_zip=None,
        files_for_fail_zip=["alpha.py"],
        failed_patch_blobs_for_zip=[],
        patch_applied_successfully=False,
        applied_ok_count=0,
        rollback_ckpt_for_posthook=ckpt,
        rollback_ws_for_posthook=ws,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["alpha.py"],
        delete_workspace_after_archive=False,
        ws_for_posthook=ws,
        push_ok_for_posthook=False,
        final_commit_sha=None,
        final_pushed_files=None,
        final_fail_stage="PATCH_APPLY",
        final_fail_reason="patch apply failed",
        primary_fail_stage="PATCH",
        primary_fail_reason="patch apply failed",
        secondary_failures=[],
    )

    post_run_mod = sys.modules[post_run_pipeline.__module__]
    rollback_calls: list[tuple[Path, object]] = []
    post_run_mod.build_artifacts = lambda **kwargs: None
    post_run_mod.rollback_to_checkpoint = lambda logger, repo, checkpoint: rollback_calls.append(
        (repo, checkpoint)
    )

    exit_code = post_run_pipeline(ctx=ctx, result=result)

    assert exit_code == 1
    assert rollback_calls == [(ws_repo, ckpt)]
    assert logger.lines.count("ROLLBACK: executed (mode=always applied_ok=0)") == 1


def test_patch_failure_rolls_back_for_none_applied_when_zero_patches_applied(
    tmp_path: Path,
) -> None:
    _, build_run_result, post_run_pipeline = _import_am_patch()
    logger = _FakeLogger()
    ctx = _ctx(tmp_path, mode="workspace", logger=logger)
    ctx.repo_root.mkdir(parents=True, exist_ok=True)
    ctx.policy.rollback_workspace_on_fail = "none-applied"

    ws_root = tmp_path / "patches" / "workspaces" / "issue_999"
    ws_repo = ws_root / "repo"
    ws_repo.mkdir(parents=True, exist_ok=True)
    ws = SimpleNamespace(root=ws_root, repo=ws_repo, attempt=1)
    ckpt = object()
    result = build_run_result(
        lock=None,
        exit_code=1,
        unified_mode=False,
        patch_script=None,
        used_patch_for_zip=None,
        files_for_fail_zip=["alpha.py"],
        failed_patch_blobs_for_zip=[],
        patch_applied_successfully=False,
        applied_ok_count=0,
        rollback_ckpt_for_posthook=ckpt,
        rollback_ws_for_posthook=ws,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["alpha.py"],
        delete_workspace_after_archive=False,
        ws_for_posthook=ws,
        push_ok_for_posthook=False,
        final_commit_sha=None,
        final_pushed_files=None,
        final_fail_stage="PATCH_APPLY",
        final_fail_reason="patch apply failed",
        primary_fail_stage="PATCH",
        primary_fail_reason="patch apply failed",
        secondary_failures=[],
    )

    post_run_mod = sys.modules[post_run_pipeline.__module__]
    rollback_calls: list[tuple[Path, object]] = []
    post_run_mod.build_artifacts = lambda **kwargs: None
    post_run_mod.rollback_to_checkpoint = lambda logger, repo, checkpoint: rollback_calls.append(
        (repo, checkpoint)
    )

    exit_code = post_run_pipeline(ctx=ctx, result=result)

    assert exit_code == 1
    assert rollback_calls == [(ws_repo, ckpt)]
    assert logger.lines.count("ROLLBACK: executed (mode=none-applied applied_ok=0)") == 1


def test_patch_failure_skips_rollback_for_none_applied_when_apply_succeeded(
    tmp_path: Path,
) -> None:
    _, build_run_result, post_run_pipeline = _import_am_patch()
    logger = _FakeLogger()
    ctx = _ctx(tmp_path, mode="workspace", logger=logger)
    ctx.repo_root.mkdir(parents=True, exist_ok=True)
    ctx.policy.rollback_workspace_on_fail = "none-applied"

    ws_root = tmp_path / "patches" / "workspaces" / "issue_999"
    ws_repo = ws_root / "repo"
    ws_repo.mkdir(parents=True, exist_ok=True)
    ws = SimpleNamespace(root=ws_root, repo=ws_repo, attempt=1)
    ckpt = object()
    result = build_run_result(
        lock=None,
        exit_code=1,
        unified_mode=False,
        patch_script=None,
        used_patch_for_zip=None,
        files_for_fail_zip=["alpha.py"],
        failed_patch_blobs_for_zip=[],
        patch_applied_successfully=True,
        applied_ok_count=1,
        rollback_ckpt_for_posthook=ckpt,
        rollback_ws_for_posthook=ws,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["alpha.py"],
        delete_workspace_after_archive=False,
        ws_for_posthook=ws,
        push_ok_for_posthook=False,
        final_commit_sha=None,
        final_pushed_files=None,
        final_fail_stage="PATCH_APPLY",
        final_fail_reason="patch apply failed",
        primary_fail_stage="PATCH",
        primary_fail_reason="patch apply failed",
        secondary_failures=[],
    )

    post_run_mod = sys.modules[post_run_pipeline.__module__]
    rollback_calls: list[tuple[Path, object]] = []
    post_run_mod.build_artifacts = lambda **kwargs: None
    post_run_mod.rollback_to_checkpoint = lambda logger, repo, checkpoint: rollback_calls.append(
        (repo, checkpoint)
    )

    exit_code = post_run_pipeline(ctx=ctx, result=result)

    assert exit_code == 1
    assert rollback_calls == []
    assert (
        logger.lines.count("ROLLBACK: skipped (mode=none-applied reason=applied-ok applied_ok=1)")
        == 1
    )
