from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_runner_script_module():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    os.environ["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"
    script_path = scripts_dir / "am_patch.py"
    module_name = "am_patch_startup_finalization_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_result_event(json_path: Path) -> dict[str, object]:
    events = [
        json.loads(line)
        for line in json_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return next(evt for evt in events if evt.get("type") == "result")


@pytest.mark.parametrize(
    (
        "failure_factory",
        "with_workspace",
        "expected_exit_code",
        "expected_stage",
        "expected_reason",
        "detail_needle",
        "fingerprint_needle",
    ),
    [
        (
            lambda errors_mod: errors_mod.RunnerCancelledError(
                "INTERNAL",
                "cancelled (cancel)",
            ),
            False,
            130,
            "INTERNAL",
            "cancel requested",
            None,
            None,
        ),
        (
            lambda errors_mod: errors_mod.RunnerCancelledError(
                "INTERNAL",
                "cancelled (cancel)",
            ),
            True,
            130,
            "INTERNAL",
            "cancel requested",
            None,
            None,
        ),
        (
            lambda errors_mod: errors_mod.RunnerError(
                "PREFLIGHT",
                "PATCH_ASCII",
                "patch contains non-ascii characters: patch.zip",
            ),
            False,
            1,
            "PREFLIGHT",
            "invalid inputs",
            "ERROR DETAIL: PREFLIGHT:PATCH_ASCII:",
            "- stage: PREFLIGHT",
        ),
        (
            lambda errors_mod: errors_mod.RunnerError(
                "PREFLIGHT",
                "PATCH_ASCII",
                "patch contains non-ascii characters: patch.zip",
            ),
            True,
            1,
            "PREFLIGHT",
            "invalid inputs",
            "ERROR DETAIL: PREFLIGHT:PATCH_ASCII:",
            "- stage: PREFLIGHT",
        ),
        (
            lambda _errors_mod: ValueError("boom"),
            False,
            1,
            "INTERNAL",
            "unexpected error",
            "ERROR DETAIL: INTERNAL:INTERNAL: ValueError: boom",
            "ValueError: boom",
        ),
        (
            lambda _errors_mod: ValueError("boom"),
            True,
            1,
            "INTERNAL",
            "unexpected error",
            "ERROR DETAIL: INTERNAL:INTERNAL: ValueError: boom",
            "ValueError: boom",
        ),
    ],
)
def test_main_finalizes_startup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_factory,
    with_workspace: bool,
    expected_exit_code: int,
    expected_stage: str,
    expected_reason: str,
    detail_needle: str | None,
    fingerprint_needle: str | None,
) -> None:
    mod = _load_runner_script_module()
    import am_patch.engine as engine_mod
    import am_patch.errors as errors_mod
    from am_patch.errors import CANCEL_EXIT_CODE
    from am_patch.log import Logger

    workspace = object() if with_workspace else None
    log_path = tmp_path / "am_patch.log"
    json_path = tmp_path / "am_patch.jsonl"
    logger = Logger(
        log_path=log_path,
        symlink_path=tmp_path / "am_patch.symlink",
        screen_level="quiet",
        log_level="quiet",
        symlink_enabled=False,
        json_enabled=True,
        json_path=json_path,
    )
    cli = SimpleNamespace(mode="workspace")
    policy = SimpleNamespace(
        test_mode=False,
        commit_and_push=False,
        ipc_socket_cleanup_delay_success_s=0,
        ipc_socket_cleanup_delay_failure_s=0,
    )
    ctx = SimpleNamespace(
        cli=cli,
        policy=policy,
        logger=logger,
        ipc=None,
        status=SimpleNamespace(stop=lambda: None),
        verbosity="quiet",
        log_level="quiet",
        log_path=log_path,
        json_path=json_path,
        isolated_work_patch_dir=None,
        effective_target_repo_name="patchhub",
        preopened_workspace=workspace,
        startup_failure=failure_factory(errors_mod),
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        mod,
        "build_effective_policy",
        lambda argv: (cli, policy, Path("cfg"), "cfg"),
    )
    monkeypatch.setattr(mod, "build_paths_and_logger", lambda *args: ctx)
    monkeypatch.setattr(
        mod,
        "run_mode",
        lambda _ctx: (_ for _ in ()).throw(AssertionError("run_mode must not run")),
    )

    def _capture_post_run_pipeline(*, ctx, result):
        captured["result"] = result
        return result.exit_code

    monkeypatch.setattr(engine_mod, "run_post_run_pipeline", _capture_post_run_pipeline)

    rc = mod.main([])

    result = captured["result"]
    result_evt = _read_result_event(json_path)

    assert rc == expected_exit_code
    assert result.exit_code == expected_exit_code
    assert result.final_fail_stage == expected_stage
    assert result.final_fail_reason == expected_reason
    assert result_evt["return_code"] == expected_exit_code
    assert result_evt["final_stage"] == expected_stage
    assert result_evt["final_reason"] == expected_reason
    if expected_exit_code == CANCEL_EXIT_CODE:
        assert result_evt["terminal_status"] == "canceled"
    else:
        assert result_evt["terminal_status"] == "fail"
    if with_workspace:
        assert result.ws_for_posthook is workspace
    else:
        assert result.ws_for_posthook is None
    if detail_needle is None:
        assert result.final_fail_detail is None
    else:
        assert detail_needle in result.final_fail_detail
    if fingerprint_needle is None:
        assert result.final_fail_fingerprint is None
    else:
        assert fingerprint_needle in result.final_fail_fingerprint
