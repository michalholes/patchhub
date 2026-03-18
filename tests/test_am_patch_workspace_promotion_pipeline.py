from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


class _FakeLogger:
    def __init__(self) -> None:
        self.sections: list[str] = []
        self.lines: list[str] = []

    def section(self, name: str) -> None:
        self.sections.append(name)

    def line(self, text: str) -> None:
        self.lines.append(text)


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.workspace_promotion_pipeline import (
        WorkspacePromotionPlan,
        complete_workspace_promotion_pipeline,
    )

    return WorkspacePromotionPlan, complete_workspace_promotion_pipeline


def test_workspace_promotion_pipeline_cleans_failure_zips_once(tmp_path: Path) -> None:
    plan_cls, complete_pipeline = _import_am_patch()
    logger = _FakeLogger()
    repo_root = tmp_path / "repo"
    workspace_repo = tmp_path / "workspace"
    repo_root.mkdir(parents=True, exist_ok=True)
    workspace_repo.mkdir(parents=True, exist_ok=True)

    policy = SimpleNamespace(
        fail_if_live_files_changed=True,
        live_changed_resolution="fail",
        commit_and_push=True,
        default_branch="main",
        allow_push_fail=False,
    )
    paths = SimpleNamespace(patch_dir=tmp_path / "patches")
    paths.patch_dir.mkdir(parents=True, exist_ok=True)

    plan = plan_cls(
        files_to_promote=["scripts/am_patch/engine.py"],
        issue_diff_base_sha="abc123",
        issue_diff_paths=["scripts/am_patch/engine.py"],
        files_for_fail_zip=["scripts/am_patch/engine.py"],
    )

    pipeline_mod = sys.modules[complete_pipeline.__module__]
    events: list[str] = []

    pipeline_mod.promote_files = lambda **kwargs: events.append("promote")
    pipeline_mod.git_ops.commit = lambda *args, **kwargs: "deadbeef"
    pipeline_mod.git_ops.push = lambda *args, **kwargs: True
    pipeline_mod.git_ops.commit_changed_files_name_status = lambda *args, **kwargs: [
        ("M", "scripts/am_patch/engine.py")
    ]
    pipeline_mod.cleanup_failure_zips_on_success = lambda **kwargs: events.append("cleanup")

    summary = complete_pipeline(
        logger=logger,
        repo_root=repo_root,
        workspace_repo=workspace_repo,
        workspace_base_sha="abc123",
        workspace_message="Issue 999: apply patch",
        paths=paths,
        policy=policy,
        issue_id="999",
        promotion_plan=plan,
        badguys_runner=lambda **kwargs: events.append("badguys"),
        live_gates_runner=lambda decision_paths: events.append("live_gates"),
        delete_workspace_after_archive=True,
    )

    assert events == ["promote", "live_gates", "badguys", "cleanup"]
    assert summary.final_commit_sha == "deadbeef"
    assert summary.push_ok_for_posthook is True
    assert summary.final_pushed_files == ["M scripts/am_patch/engine.py"]
    assert summary.delete_workspace_after_archive is True
