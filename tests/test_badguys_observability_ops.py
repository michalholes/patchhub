from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from badguys import run_suite
from badguys.bdg_evaluator import StepResult
from badguys.bdg_executor import execute_bdg_step
from badguys.bdg_loader import BdgStep, BdgTest
from badguys.bdg_materializer import MaterializedAssets
from badguys.bdg_subst import SubstCtx


def _write_config(
    repo_root: Path,
    *,
    console_verbosity: str = "quiet",
    log_verbosity: str = "quiet",
) -> Path:
    cfg_path = repo_root / "badguys" / "config_ops.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        f"""
[suite]
issue_id = "777"
runner_cmd = ["python3", "scripts/am_patch.py"]
runner_verbosity = "quiet"
console_verbosity = "{console_verbosity}"
log_verbosity = "{log_verbosity}"
patches_dir = "patches"
logs_dir = "patches/badguys_logs"
commit_limit = 0
per_run_logs_post_run = "keep_all"
suite_jail = false

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


@dataclass(frozen=True)
class _SuiteTestDef:
    name: str
    bdg: BdgTest
    makes_commit: bool = False
    is_guard: bool = False

    def run(self, _ctx) -> BdgTest:
        return self.bdg


class _SuiteTestList(list[_SuiteTestDef]):
    abort_on_guard_fail: bool
    commit_limit: int


def _suite_test_list(
    *tests: _SuiteTestDef,
    abort_on_guard_fail: bool = True,
) -> _SuiteTestList:
    out = _SuiteTestList(tests)
    out.abort_on_guard_fail = abort_on_guard_fail
    out.commit_limit = 0
    return out


def _suite_args(config_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        config=config_path.relative_to(config_path.parent.parent).as_posix(),
        commit_limit=None,
        include=[],
        exclude=[],
        list_tests=False,
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


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


def test_run_suite_continues_after_step_system_exit_and_logs_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root, console_verbosity="normal")
    args = _suite_args(cfg_path)
    cfg = run_suite._make_cfg(
        repo_root,
        Path(args.config),
        None,
        None,
        None,
        None,
        None,
    )
    central_log = run_suite._init_logs(cfg, "testrun")

    tests = _suite_test_list(
        _SuiteTestDef(
            name="test_001_step_local_fail",
            bdg=BdgTest(
                test_id="test_001_step_local_fail",
                makes_commit=False,
                is_guard=False,
                assets={},
                steps=[BdgStep(op="READ_TEXT_FILE", params={"scope": "repo", "relpath": "docs/a"})],
            ),
        ),
        _SuiteTestDef(
            name="test_002_still_runs",
            bdg=BdgTest(
                test_id="test_002_still_runs",
                makes_commit=False,
                is_guard=False,
                assets={},
                steps=[],
            ),
        ),
        abort_on_guard_fail=False,
    )

    def _fake_discover_tests(**_kwargs) -> _SuiteTestList:
        return tests

    step_calls: list[tuple[str, int]] = []

    def _fake_execute_bdg_step(**kwargs):
        test_id = str(kwargs["test_id"])
        step_index = int(kwargs["step_index"])
        step_calls.append((test_id, step_index))
        if test_id == "test_001_step_local_fail":
            raise SystemExit("FAIL: bdg: missing runner json_path: /tmp/runner_missing.jsonl")
        raise AssertionError(f"unexpected step execution for {test_id}")

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("badguys.discovery.discover_tests", _fake_discover_tests)
    monkeypatch.setattr("badguys.bdg_executor.execute_bdg_step", _fake_execute_bdg_step)
    monkeypatch.setattr(
        run_suite,
        "_load_eval_rules",
        lambda *_args, **_kwargs: {"strict_coverage": False},
    )

    rc = run_suite._run_suite_body(
        args=args,
        repo_root=repo_root,
        cfg=cfg,
        run_id="testrun",
        central_log=central_log,
    )

    assert rc == 1
    assert step_calls == [("test_001_step_local_fail", 0)]

    out = capsys.readouterr().out
    assert "BadGuys summary: FAIL passed=1 failed=1" in out
    assert "test_001_step_local_fail ... FAILED" in out
    assert "test_002_still_runs ... PASSED" in out

    fail_log = _read_jsonl(cfg.logs_dir / "test_001_step_local_fail" / "badguys.test.jsonl")
    assert {
        "type": "step_fail",
        "step_index": 0,
        "msg": "FAIL: bdg: missing runner json_path: /tmp/runner_missing.jsonl",
    } in fail_log

    pass_log = _read_jsonl(cfg.logs_dir / "test_002_still_runs" / "badguys.test.jsonl")
    assert pass_log[-1] == {
        "type": "test_end",
        "test_id": "test_002_still_runs",
        "ok": True,
    }


def test_run_suite_keeps_guard_fail_fast_for_step_system_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root, console_verbosity="normal")
    args = _suite_args(cfg_path)
    cfg = run_suite._make_cfg(
        repo_root,
        Path(args.config),
        None,
        None,
        None,
        None,
        None,
    )
    central_log = run_suite._init_logs(cfg, "testrun")

    tests = _suite_test_list(
        _SuiteTestDef(
            name="test_000_test_mode_smoke",
            bdg=BdgTest(
                test_id="test_000_test_mode_smoke",
                makes_commit=False,
                is_guard=True,
                assets={},
                steps=[BdgStep(op="READ_TEXT_FILE", params={"scope": "repo", "relpath": "docs/a"})],
            ),
            is_guard=True,
        ),
        _SuiteTestDef(
            name="test_001_not_reached",
            bdg=BdgTest(
                test_id="test_001_not_reached",
                makes_commit=False,
                is_guard=False,
                assets={},
                steps=[],
            ),
        ),
    )

    def _fake_discover_tests(**_kwargs) -> _SuiteTestList:
        return tests

    step_calls: list[tuple[str, int]] = []

    def _fake_execute_bdg_step(**kwargs):
        test_id = str(kwargs["test_id"])
        step_index = int(kwargs["step_index"])
        step_calls.append((test_id, step_index))
        raise SystemExit("FAIL: bdg: generic step failure")

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("badguys.discovery.discover_tests", _fake_discover_tests)
    monkeypatch.setattr("badguys.bdg_executor.execute_bdg_step", _fake_execute_bdg_step)
    monkeypatch.setattr(
        run_suite,
        "_load_eval_rules",
        lambda *_args, **_kwargs: {"strict_coverage": False},
    )

    rc = run_suite._run_suite_body(
        args=args,
        repo_root=repo_root,
        cfg=cfg,
        run_id="testrun",
        central_log=central_log,
    )

    assert rc == 1
    assert step_calls == [("test_000_test_mode_smoke", 0)]

    out = capsys.readouterr().out
    assert "BadGuys summary: FAIL passed=0 failed=1" in out
    assert "test_000_test_mode_smoke ... FAILED" in out
    assert "test_001_not_reached" not in out

    assert not (cfg.logs_dir / "test_001_not_reached").exists()
    summary_log = _read_jsonl(central_log)
    assert summary_log[-1] == {
        "type": "badguys_summary",
        "status": "FAIL",
        "passed": 0,
        "failed": 1,
    }


def test_run_suite_console_modes_verbose_and_debug_are_distinct_from_normal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path
    monkeypatch.setenv("NO_COLOR", "1")

    tests = _suite_test_list(
        _SuiteTestDef(
            name="test_001_step_visible",
            bdg=BdgTest(
                test_id="test_001_step_visible",
                makes_commit=False,
                is_guard=False,
                assets={},
                steps=[
                    BdgStep(
                        op="READ_TEXT_FILE",
                        params={"scope": "repo", "relpath": "docs/a"},
                    )
                ],
            ),
        ),
        abort_on_guard_fail=False,
    )

    def _fake_discover_tests(**_kwargs) -> _SuiteTestList:
        return tests

    def _fake_execute_bdg_step(**_kwargs) -> StepResult:
        return StepResult(rc=0, stdout=None, stderr=None, value="repo text\n")

    monkeypatch.setattr("badguys.discovery.discover_tests", _fake_discover_tests)
    monkeypatch.setattr("badguys.bdg_executor.execute_bdg_step", _fake_execute_bdg_step)
    monkeypatch.setattr(
        run_suite,
        "_load_eval_rules",
        lambda *_args, **_kwargs: {"strict_coverage": False},
    )

    def _run(console_verbosity: str, run_id: str) -> str:
        cfg_path = _write_config(repo_root, console_verbosity=console_verbosity)
        args = _suite_args(cfg_path)
        cfg = run_suite._make_cfg(
            repo_root,
            Path(args.config),
            None,
            None,
            None,
            None,
            None,
        )
        central_log = run_suite._init_logs(cfg, run_id)
        rc = run_suite._run_suite_body(
            args=args,
            repo_root=repo_root,
            cfg=cfg,
            run_id=run_id,
            central_log=central_log,
        )
        assert rc == 0
        return capsys.readouterr().out

    out_normal = _run("normal", "run_normal")
    out_verbose = _run("verbose", "run_verbose")
    out_debug = _run("debug", "run_debug")

    assert "BadGuys step:" not in out_normal
    assert "BadGuys debug:" not in out_normal
    assert "test_001_step_visible ... PASSED" in out_normal
    assert "BadGuys summary: OK passed=1 failed=0" in out_normal

    assert ("BadGuys step: test=test_001_step_visible step=0 op=READ_TEXT_FILE rc=0") in out_verbose
    assert "BadGuys debug:" not in out_verbose
    assert "test_001_step_visible ... PASSED" in out_verbose
    assert "BadGuys summary: OK passed=1 failed=0" in out_verbose

    assert ("BadGuys step: test=test_001_step_visible step=0 op=READ_TEXT_FILE rc=0") in out_debug
    assert (
        "BadGuys debug: config=badguys/config_ops.toml console=debug "
        "log=quiet issue=777 per_run_logs_post_run=keep_all "
        "suite_jail=false runner_cmd=python3 scripts/am_patch.py "
        "--verbosity=quiet --ipc-socket-mode=patch_dir "
        "--ipc-socket-name-template=am_patch_ipc_{issue}.sock"
    ) in out_debug
    assert "test_001_step_visible ... PASSED" in out_debug
    assert "BadGuys summary: OK passed=1 failed=0" in out_debug
