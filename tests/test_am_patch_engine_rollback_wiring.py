from __future__ import annotations

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


def test_run_mode_wires_rollback_context_for_post_workspace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, engine_mod = _import_am_patch()

    policy = policy_cls()
    policy.audit_rubric_guard = False
    policy.live_repo_guard = False
    policy.test_mode = False
    policy.allow_outside_files = False
    policy.ruff_autofix = False
    policy.biome_format = False

    logger = _FakeLogger()
    patch_root = tmp_path / "patches"
    patch_dir = patch_root / "incoming"
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_script = patch_dir / "issue_999_v2.zip"
    patch_script.write_text("x", encoding="utf-8")
    ws_root = tmp_path / "patches" / "workspaces" / "issue_999"
    ws_repo = ws_root / "repo"
    ws_repo.mkdir(parents=True, exist_ok=True)
    checkpoint = object()
    issue_state = SimpleNamespace(allowed_union=["scripts/am_patch/engine.py"])

    cli = SimpleNamespace(
        mode="workspace",
        issue_id="999",
        message="Fix rollback wiring proof",
        patch_script=None,
    )
    ctx = engine_mod.RunContext(
        cli=cli,
        policy=policy,
        config_path=tmp_path / "am_patch.toml",
        used_cfg="cfg",
        repo_root=tmp_path / "repo",
        patch_root=patch_root,
        patch_dir=patch_dir,
        isolated_work_patch_dir=None,
        paths=SimpleNamespace(
            lock_path=patch_root / ".am_patch.lock",
            symlink_path=patch_root / "current.log",
            successful_dir=patch_root / "successful",
            unsuccessful_dir=patch_root / "unsuccessful",
            workspaces_dir=patch_root / "workspaces",
            logs_dir=patch_root / "logs",
            artifacts_dir=patch_root / "artifacts",
        ),
        log_path=patch_root / "logs" / "run.log",
        json_path=None,
        logger=logger,
        status=SimpleNamespace(stop=lambda: None),
        verbosity="normal",
        log_level="normal",
        ipc=None,
    )

    monkeypatch.setattr(engine_mod, "FileLock", _FakeLock)
    monkeypatch.setattr(
        engine_mod,
        "resolve_patch_plan",
        lambda **kwargs: SimpleNamespace(
            patch_script=patch_script,
            unified_mode=False,
            files_declared=["scripts/am_patch/engine.py"],
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
                message="Issue 999: apply patch",
            ),
            checkpoint=checkpoint,
            changed_before=[],
            state_before=issue_state,
            live_guard_before=None,
        ),
    )
    monkeypatch.setattr(engine_mod, "_workspace_store_current_patch", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_mod, "run_patch", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_mod, "changed_paths", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        engine_mod,
        "enforce_scope_delta",
        lambda logger, **kwargs: ["scripts/am_patch/engine.py"],
    )
    monkeypatch.setattr(
        engine_mod,
        "update_union",
        lambda state, paths: SimpleNamespace(
            allowed_union=sorted(set(state.allowed_union) | set(paths))
        ),
    )
    monkeypatch.setattr(engine_mod, "save_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_mod, "_stage_do", lambda stage: None)
    monkeypatch.setattr(engine_mod, "_stage_ok", lambda stage: None)
    monkeypatch.setattr(engine_mod, "_stage_fail", lambda stage: None)

    def _fail_validation(**kwargs: Any) -> None:
        raise engine_mod.RunnerError("GATES", "GATES", "gate failed: pytest")

    monkeypatch.setattr(engine_mod, "run_validation", _fail_validation)

    result = engine_mod.run_mode(ctx)

    assert result.exit_code == 1
    assert result.rollback_ws_for_posthook is not None
    assert result.rollback_ws_for_posthook.root == ws_root
    assert result.rollback_ws_for_posthook.repo == ws_repo
    assert result.rollback_ckpt_for_posthook is checkpoint
    assert result.final_fail_stage == "GATE_PYTEST"
    assert result.final_fail_reason == "gates failed"
