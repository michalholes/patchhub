from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


class _FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.sections: list[str] = []

    def section(self, name: str) -> None:
        self.sections.append(name)

    def line(self, text: str) -> None:
        self.lines.append(text)


class _FakeLock:
    def __init__(self, _path: Path) -> None:
        self.acquired = 0

    def acquire(self) -> None:
        self.acquired += 1


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.engine as engine_mod
    from am_patch.config import Policy as PolicyCls

    return PolicyCls, engine_mod


def _mk_ctx(engine_mod: Any, tmp_path: Path, policy: Any, patch_script: Path) -> Any:
    patch_root = tmp_path / "patches"
    patch_dir = patch_root / "incoming"
    patch_dir.mkdir(parents=True, exist_ok=True)
    paths = SimpleNamespace(
        lock_path=patch_root / ".am_patch.lock",
        symlink_path=patch_root / "current.log",
        successful_dir=patch_root / "successful",
        unsuccessful_dir=patch_root / "unsuccessful",
        workspaces_dir=patch_root / "workspaces",
        logs_dir=patch_root / "logs",
        artifacts_dir=patch_root / "artifacts",
    )
    return engine_mod.RunContext(
        cli=SimpleNamespace(
            mode="workspace",
            issue_id="361",
            message="Fix gate step-local legalization capture in AMP",
            patch_script=None,
        ),
        policy=policy,
        config_path=tmp_path / "am_patch.toml",
        used_cfg="cfg",
        repo_root=tmp_path / "repo",
        patch_root=patch_root,
        patch_dir=patch_dir,
        isolated_work_patch_dir=None,
        paths=paths,
        log_path=patch_root / "logs" / "run.log",
        json_path=None,
        logger=_FakeLogger(),
        status=SimpleNamespace(stop=lambda: None),
        verbosity="normal",
        log_level="normal",
        ipc=None,
        runner_root=tmp_path,
        artifacts_root=patch_root,
        active_repository_tree_root=tmp_path / "repo",
        live_target_root=tmp_path / "repo",
        effective_target_repo_name="patchhub",
        preopened_workspace=None,
    )


def _prepare_common(
    monkeypatch: pytest.MonkeyPatch,
    engine_mod: Any,
    ctx: Any,
    tmp_path: Path,
) -> tuple[Path, Path]:
    patch_script = ctx.patch_dir / "issue_361_v1.zip"
    patch_script.write_text("x", encoding="utf-8")
    ws_root = ctx.paths.workspaces_dir / "issue_361"
    ws_repo = ws_root / "repo"
    ws_repo.mkdir(parents=True, exist_ok=True)
    checkpoint = object()

    monkeypatch.setattr(engine_mod, "FileLock", _FakeLock)
    monkeypatch.setattr(
        engine_mod,
        "resolve_patch_plan",
        lambda **kwargs: SimpleNamespace(
            patch_script=patch_script,
            unified_mode=False,
            files_declared=["declared.py"],
        ),
    )
    monkeypatch.setattr(engine_mod, "policy_for_log", lambda policy: "policy")
    monkeypatch.setattr(engine_mod, "check_audit_rubric_coverage", lambda repo_root: [])
    monkeypatch.setattr(
        engine_mod,
        "open_execution_context",
        lambda **kwargs: SimpleNamespace(
            ws=SimpleNamespace(
                root=ws_root,
                repo=ws_repo,
                attempt=1,
                base_sha="abc123",
                message="Issue 361: apply patch",
            ),
            checkpoint=checkpoint,
            changed_before=[],
            state_before=SimpleNamespace(base_sha="abc123", allowed_union=set()),
            live_guard_before=None,
        ),
    )
    monkeypatch.setattr(engine_mod, "_workspace_store_current_patch", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_mod, "archive_patch", lambda *args, **kwargs: patch_script)
    monkeypatch.setattr(engine_mod, "drop_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_mod, "_stage_do", lambda stage: None)
    monkeypatch.setattr(engine_mod, "_stage_ok", lambda stage: None)
    monkeypatch.setattr(engine_mod, "_stage_fail", lambda stage: None)
    monkeypatch.setattr(
        engine_mod,
        "enforce_scope_delta",
        lambda logger, **kwargs: ["declared.py"],
    )
    monkeypatch.setattr(
        engine_mod,
        "complete_workspace_promotion_pipeline",
        lambda **kwargs: SimpleNamespace(
            issue_diff_base_sha="abc123",
            issue_diff_paths=["declared.py"],
            files_for_fail_zip=list(kwargs["promotion_plan"].files_for_fail_zip),
            push_ok_for_posthook=True,
            final_commit_sha="def456",
            final_pushed_files=["declared.py"],
            delete_workspace_after_archive=False,
        ),
    )
    return patch_script, ws_root


def test_run_mode_persists_gate_step_capture_before_gate_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, engine_mod = _import_am_patch()
    policy = policy_cls()
    policy.audit_rubric_guard = False
    policy.live_repo_guard = False
    policy.test_mode = False
    policy.allow_outside_files = False
    policy.ruff_targets = ["tests"]
    policy.ruff_format = True
    policy.ruff_autofix = False
    patch_script = tmp_path / "placeholder.zip"
    ctx = _mk_ctx(engine_mod, tmp_path, policy, patch_script)
    _, ws_root = _prepare_common(monkeypatch, engine_mod, ctx, tmp_path)

    monkeypatch.setattr(engine_mod, "run_patch", lambda *args, **kwargs: None)
    changed_returns = iter([["declared.py"], ["declared.py"]])
    monkeypatch.setattr(
        engine_mod,
        "changed_paths",
        lambda *args, **kwargs: list(next(changed_returns)),
    )

    def _fail_validation(**kwargs: Any) -> None:
        kwargs["gate_step_callback"](
            step_key="ruff_format",
            pre_dirty=["declared.py"],
            post_dirty=["declared.py", "tests/formatted.py"],
        )
        raise engine_mod.RunnerError("GATES", "GATES", "gate failed: pytest")

    monkeypatch.setattr(engine_mod, "run_validation", _fail_validation)

    result = engine_mod.run_mode(ctx)
    state = json.loads((ws_root / ".am_patch_state.json").read_text(encoding="utf-8"))

    assert result.exit_code == 1
    assert result.files_for_fail_zip == ["declared.py", "tests/formatted.py"]
    assert state["allowed_union"] == ["declared.py", "tests/formatted.py"]
    assert "gate_step_legalized_ruff_format=['tests/formatted.py']" in ctx.logger.lines
    assert "legalized_ruff_autofix_files=['tests/formatted.py']" in ctx.logger.lines
    assert result.final_fail_stage == "GATE_PYTEST"
    assert result.final_fail_reason == "gates failed"


def test_run_mode_persists_gate_step_capture_before_deferred_patch_apply_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, engine_mod = _import_am_patch()
    policy = policy_cls()
    policy.audit_rubric_guard = False
    policy.live_repo_guard = False
    policy.test_mode = False
    policy.allow_outside_files = False
    policy.apply_failure_partial_gates_policy = "always"
    policy.ruff_targets = ["tests"]
    policy.ruff_format = True
    policy.ruff_autofix = False
    patch_script = tmp_path / "placeholder.zip"
    ctx = _mk_ctx(engine_mod, tmp_path, policy, patch_script)
    _, ws_root = _prepare_common(monkeypatch, engine_mod, ctx, tmp_path)

    def _fail_patch(*args: Any, **kwargs: Any) -> None:
        raise engine_mod.RunnerError("PATCH", "PATCH_APPLY", "patch apply failed")

    monkeypatch.setattr(engine_mod, "run_patch", _fail_patch)
    changed_returns = iter([["declared.py"], ["declared.py"]])
    monkeypatch.setattr(
        engine_mod,
        "changed_paths",
        lambda *args, **kwargs: list(next(changed_returns)),
    )

    def _validation(**kwargs: Any) -> None:
        kwargs["gate_step_callback"](
            step_key="ruff_format",
            pre_dirty=["declared.py"],
            post_dirty=["declared.py", "tests/formatted.py"],
        )

    monkeypatch.setattr(engine_mod, "run_validation", _validation)

    result = engine_mod.run_mode(ctx)
    state = json.loads((ws_root / ".am_patch_state.json").read_text(encoding="utf-8"))

    assert result.exit_code == 1
    assert result.files_for_fail_zip == ["declared.py", "tests/formatted.py"]
    assert state["allowed_union"] == ["declared.py", "tests/formatted.py"]
    assert "gate_step_legalized_ruff_format=['tests/formatted.py']" in ctx.logger.lines
    assert result.final_fail_stage == "PATCH_APPLY"
    assert result.final_fail_reason == "patch apply failed"


def test_run_mode_keeps_gate_step_capture_on_cancel_without_post_hoc_reconcile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, engine_mod = _import_am_patch()
    policy = policy_cls()
    policy.audit_rubric_guard = False
    policy.live_repo_guard = False
    policy.test_mode = False
    policy.allow_outside_files = False
    policy.ruff_targets = ["tests"]
    policy.ruff_format = True
    policy.ruff_autofix = False
    patch_script = tmp_path / "placeholder.zip"
    ctx = _mk_ctx(engine_mod, tmp_path, policy, patch_script)
    _, ws_root = _prepare_common(monkeypatch, engine_mod, ctx, tmp_path)

    monkeypatch.setattr(engine_mod, "run_patch", lambda *args, **kwargs: None)
    changed_returns = iter([["declared.py"]])
    monkeypatch.setattr(
        engine_mod,
        "changed_paths",
        lambda *args, **kwargs: list(next(changed_returns)),
    )

    def _cancel_validation(**kwargs: Any) -> None:
        kwargs["gate_step_callback"](
            step_key="ruff_format",
            pre_dirty=["declared.py"],
            post_dirty=["declared.py", "tests/formatted.py"],
        )
        raise engine_mod.RunnerCancelledError("GATES", "subprocess canceled (ruff)")

    monkeypatch.setattr(engine_mod, "run_validation", _cancel_validation)

    result = engine_mod.run_mode(ctx)
    state = json.loads((ws_root / ".am_patch_state.json").read_text(encoding="utf-8"))

    assert result.exit_code == engine_mod.CANCEL_EXIT_CODE
    assert result.files_for_fail_zip == ["declared.py", "tests/formatted.py"]
    assert state["allowed_union"] == ["declared.py", "tests/formatted.py"]
    assert result.final_fail_stage == "GATES"
    assert result.final_fail_reason == "cancel requested"


def test_gate_step_capture_sink_skips_redundant_state_write_for_already_legalized_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, engine_mod = _import_am_patch()
    from am_patch.state import IssueState

    policy = policy_cls()
    policy.ruff_targets = ["tests"]
    policy.ruff_format = True
    policy.ruff_autofix = False

    logger = _FakeLogger()
    state = IssueState(base_sha="abc123", allowed_union={"declared.py", "tests/formatted.py"})
    save_calls: list[list[str]] = []

    def _record_save(_workspace_root: Path, current_state: Any) -> None:
        save_calls.append(sorted(current_state.allowed_union))

    monkeypatch.setattr(engine_mod, "save_state", _record_save)

    next_state, files_for_fail_zip = engine_mod._gate_step_capture_sink(
        logger=logger,
        policy=policy,
        workspace_root=tmp_path,
        state=state,
        files_for_fail_zip=["declared.py"],
        step_key="ruff_format",
        pre_dirty=["declared.py"],
        post_dirty=["declared.py", "tests/formatted.py"],
    )

    assert next_state is state
    assert save_calls == []
    assert files_for_fail_zip == ["declared.py", "tests/formatted.py"]
    assert state.allowed_union == {"declared.py", "tests/formatted.py"}
    assert logger.lines == ["gate_step_legalized_ruff_format=[]"]


def test_gate_step_capture_sink_does_not_emit_legalized_logs_before_state_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, engine_mod = _import_am_patch()
    from am_patch.state import IssueState

    policy = policy_cls()
    policy.ruff_targets = ["tests"]
    policy.ruff_format = True
    policy.ruff_autofix = False

    logger = _FakeLogger()
    state = IssueState(base_sha="abc123", allowed_union={"declared.py"})

    def _fail_save(_workspace_root: Path, _current_state: Any) -> None:
        raise OSError("diskfull")

    monkeypatch.setattr(engine_mod, "save_state", _fail_save)

    with pytest.raises(OSError, match="diskfull"):
        engine_mod._gate_step_capture_sink(
            logger=logger,
            policy=policy,
            workspace_root=tmp_path,
            state=state,
            files_for_fail_zip=["declared.py"],
            step_key="ruff_format",
            pre_dirty=["declared.py"],
            post_dirty=["declared.py", "tests/formatted.py"],
        )

    assert state.allowed_union == {"declared.py"}
    assert logger.lines == []
