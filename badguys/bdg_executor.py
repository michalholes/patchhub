from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
import time
from pathlib import Path

from badguys.bdg_evaluator import StepResult
from badguys.bdg_loader import BdgStep, BdgTest
from badguys.bdg_materializer import MaterializedAssets
from badguys.bdg_ops_files import (
    execute_read_step_log,
    execute_read_text_file,
    execute_zip_list,
)
from badguys.bdg_ops_git import execute_git_status_porcelain
from badguys.bdg_ops_ipc import (
    execute_ipc_send_command,
    pop_ipc_plans,
    runner_socket_name,
    runner_socket_path,
)
from badguys.bdg_recipe import ensure_allowed_keys, step_recipe
from badguys.bdg_subst import SubstCtx, subst_text


def _subst(value: str, *, subst: SubstCtx) -> str:
    return subst_text(value, ctx=subst)


def _safe_name(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum() or ch in {"_", "-", "."}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _lock_path_for_test(repo_root: Path, *, test_id: str) -> Path:
    safe = _safe_name(test_id)
    return repo_root / "patches" / f"{safe}.lock"


def _outside_sentinel(repo_root: Path, *, issue_id: str) -> Path:
    return repo_root.parent / f"badguys_sentinel_issue_{issue_id}.txt"


def _workspace_root(patch_root: Path, *, issue_id: str) -> Path:
    return patch_root / "workspaces" / f"issue_{issue_id}"


def _workspace_repo(patch_root: Path, *, issue_id: str) -> Path:
    return _workspace_root(patch_root, issue_id=issue_id) / "repo"


def _git_stdout(*, cwd: Path, argv: list[str], label: str) -> str:
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return (proc.stdout or "").strip()
    detail = (proc.stderr or proc.stdout or "").strip()
    if not detail:
        detail = "command failed"
    raise SystemExit(f"FAIL: bdg: {label}: {detail}")


def _ensure_runner_workspace_repo(
    repo_root: Path,
    *,
    patch_root: Path,
    issue_id: str,
) -> Path:
    ws_repo = _workspace_repo(patch_root, issue_id=issue_id)
    if ws_repo.exists():
        if not ws_repo.is_dir():
            raise SystemExit(f"FAIL: bdg: workspace repo is not directory: {ws_repo}")
        return ws_repo

    ws_root = _workspace_root(patch_root, issue_id=issue_id)
    ws_root.mkdir(parents=True, exist_ok=True)
    base_sha = _git_stdout(
        cwd=repo_root,
        argv=["git", "rev-parse", "HEAD"],
        label="unable to resolve live repo HEAD for workspace bootstrap",
    )
    _git_stdout(
        cwd=repo_root,
        argv=["git", "clone", str(repo_root), str(ws_repo)],
        label="git clone failed while bootstrapping workspace",
    )
    _git_stdout(
        cwd=ws_repo,
        argv=["git", "checkout", base_sha],
        label=(f"git checkout failed while bootstrapping workspace at {base_sha}"),
    )
    return ws_repo


def execute_bdg(
    *,
    repo_root: Path,
    config_path: Path,
    cfg_runner_cmd: list[str],
    subst: SubstCtx,
    full_runner_tests: set[str],
    bdg: BdgTest,
    mats: MaterializedAssets,
    step_runner_cfg: dict[str, object],
) -> list[StepResult]:
    results: list[StepResult] = []
    for idx, step in enumerate(bdg.steps):
        results.append(
            _exec_one(
                repo_root=repo_root,
                config_path=config_path,
                cfg_runner_cmd=cfg_runner_cmd,
                subst=subst,
                full_runner_tests=full_runner_tests,
                step=step,
                mats=mats,
                test_id=bdg.test_id,
                step_index=int(idx),
                step_runner_cfg=step_runner_cfg,
            )
        )
    return results


def execute_bdg_step(
    *,
    repo_root: Path,
    config_path: Path,
    cfg_runner_cmd: list[str],
    subst: SubstCtx,
    full_runner_tests: set[str],
    step: BdgStep,
    mats: MaterializedAssets,
    test_id: str,
    step_index: int,
    step_runner_cfg: dict[str, object],
) -> StepResult:
    return _exec_one(
        repo_root=repo_root,
        config_path=config_path,
        cfg_runner_cmd=cfg_runner_cmd,
        subst=subst,
        full_runner_tests=full_runner_tests,
        step=step,
        mats=mats,
        test_id=test_id,
        step_index=int(step_index),
        step_runner_cfg=step_runner_cfg,
    )


def _artifacts_dir(step_runner_cfg: dict[str, object]) -> Path:
    out = step_runner_cfg.get("artifacts_dir")
    if not isinstance(out, Path):
        raise SystemExit("FAIL: bdg: artifacts_dir must be Path")
    return out


def _patches_dir(step_runner_cfg: dict[str, object]) -> Path:
    out = step_runner_cfg.get("patches_dir")
    if not isinstance(out, Path):
        raise SystemExit("FAIL: bdg: patches_dir must be Path")
    return out


def _runner_patch_dir(step_runner_cfg: dict[str, object]) -> Path | None:
    out = step_runner_cfg.get("runner_patch_dir")
    if out is None:
        return None
    if not isinstance(out, Path):
        raise SystemExit("FAIL: bdg: runner_patch_dir must be Path")
    return out


def _exec_one(
    *,
    repo_root: Path,
    config_path: Path,
    cfg_runner_cmd: list[str],
    subst: SubstCtx,
    full_runner_tests: set[str],
    step: BdgStep,
    mats: MaterializedAssets,
    test_id: str,
    step_index: int,
    step_runner_cfg: dict[str, object],
) -> StepResult:
    op = step.op
    p = step.params
    if op == "RUN_RUNNER":
        input_asset = p.get("input_asset")
        if input_asset is not None and not isinstance(input_asset, str):
            raise SystemExit("FAIL: bdg: input_asset must be string")
        if isinstance(input_asset, str):
            input_asset = _subst(input_asset, subst=subst)
        recipe = step_recipe(
            repo_root=repo_root,
            config_path=config_path,
            test_id=test_id,
            step_index=step_index,
        )
        ensure_allowed_keys(
            table=recipe,
            allowed={"args"},
            label=f"recipes.tests.{test_id}.steps.{step_index}",
        )
        extra_args = recipe.get("args", [])
        if not (isinstance(extra_args, list) and all(isinstance(x, str) for x in extra_args)):
            raise SystemExit(
                "FAIL: bdg recipe: RUN_RUNNER args for "
                f"{test_id} step {step_index} must be list[str]"
            )
        if "--test-mode" in extra_args:
            raise SystemExit(
                "FAIL: bdg recipe: --test-mode is controlled by BadGuys; remove it from args"
            )

        patches_dir = _patches_dir(step_runner_cfg)
        runner_patch_dir = _runner_patch_dir(step_runner_cfg)
        artifacts_dir = _artifacts_dir(step_runner_cfg)
        copy_runner_log = bool(step_runner_cfg.get("copy_runner_log", False))
        write_subprocess_stdio = bool(step_runner_cfg.get("write_subprocess_stdio", False))
        console_verbosity = str(step_runner_cfg.get("console_verbosity", "normal"))
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        argv = list(cfg_runner_cmd)
        if runner_patch_dir is not None:
            argv.extend(["--override", f"patch_dir={runner_patch_dir}"])
        if test_id not in full_runner_tests:
            argv.append("--test-mode")
        argv.extend([_subst(a, subst=subst) for a in extra_args])
        if input_asset:
            path = mats.files.get(input_asset)
            if path is None:
                raise SystemExit(f"FAIL: bdg: missing materialized asset: {input_asset}")
            argv.append(str(path))

        socket_name = runner_socket_name(argv=argv, issue_id=subst.issue_id)
        ipc_stream_path = artifacts_dir / f"runner.ipc.step{int(step_index)}.jsonl"
        ipc_holder: dict[str, object] = {"result": None, "value_text": ""}
        socket_base_dir = runner_patch_dir or patches_dir
        socket_path_holder: dict[str, Path] = {"path": socket_base_dir / socket_name}

        plans = pop_ipc_plans(step_runner_cfg)

        def _run_recorder() -> None:
            from badguys.ipc_stream_recorder import record_ipc_stream

            command_plans: list[dict[str, object]] = []
            for plan in plans:
                command_plans.append(
                    {
                        "protocol": "am_patch_ipc/1",
                        "step_index": int(plan.step_index),
                        "cmd": plan.cmd,
                        "cmd_id": plan.cmd_id,
                        "args": dict(plan.args),
                        "delay_s": float(plan.delay_s),
                        "wait_event_type": plan.wait_event_type,
                        "wait_event_name": plan.wait_event_name,
                        "event_arg_map": dict(plan.event_arg_map),
                        "request_path": (
                            artifacts_dir / f"ipc_request.step{int(plan.step_index)}.json"
                        ),
                        "reply_path": artifacts_dir / f"ipc_reply.step{int(plan.step_index)}.json",
                    }
                )

            res, value_text, artifact_copy = record_ipc_stream(
                socket_path_holder["path"],
                out_path=ipc_stream_path,
                connect_timeout_s=3.0,
                total_timeout_s=0.0,
                command_plans=command_plans,
                result_json_copy_path=artifacts_dir / "runner.result.json",
                runner_jsonl_copy_path=artifacts_dir / "runner.log.jsonl",
                runner_log_copy_path=(
                    artifacts_dir / "runner.log.txt" if copy_runner_log else None
                ),
            )
            ipc_holder["result"] = res
            ipc_holder["value_text"] = value_text
            ipc_holder["artifact_copy"] = artifact_copy

        heartbeat_enabled = console_verbosity in {"normal", "verbose", "debug"}
        started = time.monotonic()
        last_msg: str | None = None

        proc = subprocess.Popen(
            argv,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if runner_patch_dir is not None:
            socket_path_holder["path"] = runner_patch_dir / socket_name
        else:
            socket_path_holder["path"] = runner_socket_path(
                patches_dir=patches_dir,
                issue_id=subst.issue_id,
                socket_name=socket_name,
                test_mode=(test_id not in full_runner_tests),
                runner_pid=proc.pid,
            )

        ipc_thread = threading.Thread(
            target=_run_recorder,
            name="badguys_ipc_recorder",
            daemon=True,
        )
        ipc_thread.start()

        stdout = ""
        stderr = ""

        def _emit_hb(msg: str) -> None:
            nonlocal last_msg
            out = msg
            if sys.stderr.isatty():
                pad = ""
                if last_msg is not None and len(last_msg) > len(out):
                    pad = " " * (len(last_msg) - len(out))
                sys.stderr.write("\r" + out + pad)
                sys.stderr.flush()
            else:
                sys.stderr.write("HEARTBEAT: " + out + "\n")
                sys.stderr.flush()
            last_msg = out

        def _clear_hb() -> None:
            if not sys.stderr.isatty() or last_msg is None:
                return
            sys.stderr.write("\r" + (" " * len(last_msg)) + "\r")
            sys.stderr.flush()

        try:
            while True:
                try:
                    if heartbeat_enabled:
                        stdout, stderr = proc.communicate(timeout=5.0)
                    else:
                        stdout, stderr = proc.communicate()
                    break
                except subprocess.TimeoutExpired:
                    elapsed = int(time.monotonic() - started)
                    mm, ss = divmod(elapsed, 60)
                    _emit_hb(f"BadGuys {test_id} step={int(step_index)} ELAPSED: {mm:02d}:{ss:02d}")
                    continue
                except KeyboardInterrupt:
                    with contextlib.suppress(Exception):
                        if proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.wait(timeout=2.0)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                    raise
        finally:
            _clear_hb()

        rc = int(proc.returncode or 0)
        ipc_thread.join(timeout=2.0)
        ipc_result = ipc_holder.get("result")
        value_text = str(ipc_holder.get("value_text") or "")

        if isinstance(ipc_result, dict):
            with contextlib.suppress(Exception):
                rc = int(ipc_result["return_code"])

            artifact_copy = ipc_holder.get("artifact_copy")
            if isinstance(artifact_copy, dict) and not bool(artifact_copy.get("ok", False)):
                error = str(artifact_copy.get("error") or "runner artifact copy failed")
                raise SystemExit(f"FAIL: bdg: {error}")

        if write_subprocess_stdio:
            if stdout:
                (artifacts_dir / "runner.stdout.txt").write_text(stdout, encoding="utf-8")
            if stderr:
                (artifacts_dir / "runner.stderr.txt").write_text(stderr, encoding="utf-8")

        return StepResult(rc=rc, stdout=None, stderr=None, value=value_text)

    if op == "DISCOVER_TESTS":
        from badguys.discovery import discover_tests

        include = p.get("include", [])
        exclude = p.get("exclude", [])
        if not (isinstance(include, list) and all(isinstance(x, str) for x in include)):
            raise SystemExit("FAIL: bdg: include must be list[str]")
        if not (isinstance(exclude, list) and all(isinstance(x, str) for x in exclude)):
            raise SystemExit("FAIL: bdg: exclude must be list[str]")
        include = [_subst(x, subst=subst) for x in include]
        exclude = [_subst(x, subst=subst) for x in exclude]
        try:
            tests = discover_tests(
                repo_root=repo_root,
                config_path=config_path,
                cli_commit_limit=None,
                cli_include=list(include),
                cli_exclude=list(exclude),
            )
        except SystemExit as e:
            return StepResult(rc=2, stdout=None, stderr=str(e), value=None)
        names = [t.name for t in tests]
        return StepResult(rc=0, stdout=None, stderr=None, value=names)

    if op == "BUILD_CFG":
        input_asset = p.get("input_asset")
        if not isinstance(input_asset, str):
            raise SystemExit("FAIL: bdg: BUILD_CFG requires input_asset")
        input_asset = _subst(input_asset, subst=subst)
        cfg_path = mats.files.get(input_asset)
        if cfg_path is None:
            raise SystemExit(f"FAIL: bdg: missing materialized asset: {input_asset}")

        recipe = step_recipe(
            repo_root=repo_root,
            config_path=config_path,
            test_id=test_id,
            step_index=step_index,
        )
        ensure_allowed_keys(
            table=recipe,
            allowed={
                "commit_limit",
                "console_verbosity",
                "log_verbosity",
                "runner_verbosity",
            },
            label=f"recipes.tests.{test_id}.steps.{step_index}",
        )
        cli_runner_verbosity = recipe.get("runner_verbosity")
        cli_console_verbosity = recipe.get("console_verbosity")
        cli_log_verbosity = recipe.get("log_verbosity")
        cli_commit_limit = recipe.get("commit_limit")

        for key, val in [
            ("runner_verbosity", cli_runner_verbosity),
            ("console_verbosity", cli_console_verbosity),
            ("log_verbosity", cli_log_verbosity),
        ]:
            if val is not None and not isinstance(val, str):
                raise SystemExit(f"FAIL: bdg recipe: {key} must be string or omitted")
        if cli_commit_limit is not None and not isinstance(cli_commit_limit, int):
            raise SystemExit("FAIL: bdg recipe: commit_limit must be int or omitted")

        from badguys.run_suite import _make_cfg

        cfg = _make_cfg(
            repo_root,
            cfg_path.relative_to(repo_root),
            cli_runner_verbosity,
            cli_console_verbosity,
            cli_log_verbosity,
            None,
        )
        runner_cmd = list(cfg.runner_cmd)
        if cli_commit_limit is not None:
            runner_cmd.append(f"--commit-limit={cli_commit_limit}")
        joined = " ".join(runner_cmd)
        return StepResult(rc=0, stdout=None, stderr=None, value=joined)

    if op == "READ_STEP_LOG":
        name = p.get("test_name")
        if name is None:
            name = test_id
        if not isinstance(name, str):
            raise SystemExit("FAIL: bdg: test_name must be string")
        return execute_read_step_log(
            repo_root=repo_root,
            config_path=config_path,
            test_name=_subst(name, subst=subst),
        )

    if op == "READ_TEXT_FILE":
        return execute_read_text_file(
            repo_root=repo_root,
            step=p,
            artifacts_dir=_artifacts_dir(step_runner_cfg),
            issue_id=subst.issue_id,
        )

    if op == "ZIP_LIST":
        return execute_zip_list(
            repo_root=repo_root,
            step=p,
            artifacts_dir=_artifacts_dir(step_runner_cfg),
            issue_id=subst.issue_id,
        )

    if op == "IPC_SEND_COMMAND":
        return execute_ipc_send_command(
            step_runner_cfg=step_runner_cfg,
            params=p,
            test_id=test_id,
            step_index=step_index,
        )

    if op == "LOCK_DELETE":
        lock_path = _lock_path_for_test(repo_root, test_id=test_id)
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()
        return StepResult(rc=0, stdout=None, stderr=None, value=str(lock_path))

    if op == "LOCK_WRITE_STALE":
        lock_path = _lock_path_for_test(repo_root, test_id=test_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("pid=0\nstarted=0\n", encoding="utf-8")
        return StepResult(rc=0, stdout=None, stderr=None, value=str(lock_path))

    if op == "LOCK_ACQUIRE":
        ttl_seconds = p.get("ttl_seconds")
        on_conflict = p.get("on_conflict")
        if not isinstance(ttl_seconds, int):
            raise SystemExit("FAIL: bdg: ttl_seconds must be int")
        if not isinstance(on_conflict, str):
            raise SystemExit("FAIL: bdg: on_conflict must be 'fail' or 'steal'")
        on_conflict = _subst(on_conflict, subst=subst)
        if on_conflict not in {"fail", "steal"}:
            raise SystemExit("FAIL: bdg: on_conflict must be 'fail' or 'steal'")
        lock_path = _lock_path_for_test(repo_root, test_id=test_id)
        from badguys._util import acquire_lock

        try:
            acquire_lock(
                repo_root,
                path=lock_path,
                ttl_seconds=ttl_seconds,
                on_conflict=on_conflict,
            )
        except SystemExit as e:
            return StepResult(rc=1, stdout=None, stderr=str(e), value=str(lock_path))
        return StepResult(rc=0, stdout=None, stderr=None, value=str(lock_path))

    if op == "LOCK_RELEASE":
        lock_path = _lock_path_for_test(repo_root, test_id=test_id)
        from badguys._util import release_lock

        try:
            release_lock(repo_root, path=lock_path)
        except SystemExit as e:
            return StepResult(rc=1, stdout=None, stderr=str(e), value=str(lock_path))
        return StepResult(rc=0, stdout=None, stderr=None, value=str(lock_path))

    if op == "CLEAN_OUTSIDE_SENTINEL":
        sentinel = _outside_sentinel(repo_root, issue_id=subst.issue_id)
        with contextlib.suppress(FileNotFoundError):
            sentinel.unlink()
        return StepResult(rc=0, stdout=None, stderr=None, value=str(sentinel))

    if op == "DELETE_REPO_COMMIT_MARKER":
        marker = repo_root / "badguys" / "artifacts" / "commit_marker.txt"
        with contextlib.suppress(FileNotFoundError):
            marker.unlink()
        return StepResult(rc=0, stdout=None, stderr=None, value=str(marker))

    if op == "ASSERT_NO_OUTSIDE_SENTINEL":
        sentinel = _outside_sentinel(repo_root, issue_id=subst.issue_id)
        if sentinel.exists():
            return StepResult(
                rc=1,
                stdout=None,
                stderr="outside write detected",
                value=str(sentinel),
            )
        return StepResult(rc=0, stdout=None, stderr=None, value=str(sentinel))

    if op == "DELETE_PATCHED_ZIP":
        patched_zip = repo_root / "patches" / "patched.zip"
        with contextlib.suppress(FileNotFoundError):
            patched_zip.unlink()
        return StepResult(rc=0, stdout=None, stderr=None, value=str(patched_zip))

    if op == "DELETE_SUBJECT":
        subject = p.get("subject")
        if not isinstance(subject, str) or not subject:
            raise SystemExit(
                f"FAIL: bdg: DELETE_SUBJECT subject missing for {test_id} step {step_index}"
            )
        target_rel = mats.subjects.get(subject)
        if target_rel is None:
            raise SystemExit(f"FAIL: bdg: unknown subject '{subject}' for {test_id}")
        patches_dir = _patches_dir(step_runner_cfg)
        step_runner_cfg["runner_patch_dir"] = patches_dir
        workspace_repo = _ensure_runner_workspace_repo(
            repo_root,
            patch_root=patches_dir,
            issue_id=subst.issue_id,
        )
        target_path = workspace_repo / target_rel
        if target_path.is_symlink():
            target_path.unlink()
            return StepResult(rc=0, stdout=None, stderr=None, value=str(target_path))
        if not target_path.exists():
            return StepResult(rc=0, stdout=None, stderr=None, value=str(target_path))
        if target_path.is_dir():
            return StepResult(
                rc=1,
                stdout=None,
                stderr="DELETE_SUBJECT target is directory",
                value=str(target_path),
            )
        target_path.unlink()
        return StepResult(rc=0, stdout=None, stderr=None, value=str(target_path))

    if op == "ASSERT_NO_WORKSPACE_AND_NO_ARCHIVES":
        ws_dir = repo_root / "patches" / "workspaces" / f"issue_{subst.issue_id}"
        patched_zip = repo_root / "patches" / "patched.zip"
        if ws_dir.exists():
            return StepResult(rc=1, stdout=None, stderr="workspace exists", value=str(ws_dir))
        if patched_zip.exists():
            return StepResult(
                rc=1,
                stdout=None,
                stderr="patched.zip exists",
                value=str(patched_zip),
            )
        return StepResult(rc=0, stdout=None, stderr=None, value="OK")

    if op == "ASSERT_WORKSPACE_REPO_EXISTS":
        ws_repo = repo_root / "patches" / "workspaces" / f"issue_{subst.issue_id}" / "repo"
        if not ws_repo.exists():
            return StepResult(
                rc=1,
                stdout=None,
                stderr="missing workspace repo",
                value=str(ws_repo),
            )
        return StepResult(rc=0, stdout=None, stderr=None, value=str(ws_repo))

    if op == "GIT_STATUS_PORCELAIN":
        scope = p.get("scope", "root")
        if not isinstance(scope, str):
            raise SystemExit("FAIL: bdg: scope must be 'root' or 'workspace'")
        return execute_git_status_porcelain(
            repo_root=repo_root,
            issue_id=subst.issue_id,
            scope=_subst(scope, subst=subst),
        )

    if op == "PREPARE_UNSUCCESSFUL_PATCH":
        marker_subject = p.get("marker_subject")
        if not isinstance(marker_subject, str) or not marker_subject:
            raise SystemExit(
                "FAIL: bdg: PREPARE_UNSUCCESSFUL_PATCH marker_subject "
                f"missing for {test_id} step {step_index}"
            )
        marker_rel = mats.subjects.get(marker_subject)
        if marker_rel is None:
            raise SystemExit(f"FAIL: bdg: unknown marker_subject '{marker_subject}' for {test_id}")
        marker_text = p.get("marker_text", "")
        if not isinstance(marker_text, str):
            raise SystemExit("FAIL: bdg: marker_text must be string")
        marker_text = _subst(marker_text, subst=subst)
        unsucc_dir = repo_root / "patches" / "unsuccessful"
        unsucc_dir.mkdir(parents=True, exist_ok=True)
        name = f"issue_{subst.issue_id}__badguys_rerun_latest__bdg.patch"
        patch_path = unsucc_dir / name
        patch_txt = (
            f"diff --git a/{marker_rel} b/{marker_rel}\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            f"--- /dev/null\n"
            f"+++ b/{marker_rel}\n"
            "@@ -0,0 +1 @@\n"
            f"+{marker_text}\n"
        )
        patch_path.write_text(patch_txt, encoding="utf-8")
        return StepResult(rc=0, stdout=None, stderr=None, value=str(patch_path))

    if op == "PREPARE_LATEST_BUNDLE_900":
        issue = str(subst.issue_id)
        stamp_raw = p.get("stamp", "${now_stamp}")
        if not isinstance(stamp_raw, str):
            raise SystemExit("FAIL: bdg: stamp must be string")
        stamp = _subst(stamp_raw, subst=subst)
        if "\n" in stamp or "\r" in stamp:
            raise SystemExit("FAIL: bdg: stamp must not contain newlines")
        patches_dir = repo_root / "patches"
        patches_dir.mkdir(parents=True, exist_ok=True)
        ws_repo = patches_dir / "workspaces" / f"issue_{issue}" / "repo"
        marker_subject = p.get("marker_subject")
        seed_subject = p.get("seed_subject")
        if not isinstance(marker_subject, str) or not isinstance(seed_subject, str):
            raise SystemExit(
                "FAIL: bdg: PREPARE_LATEST_BUNDLE_900 subjects missing "
                f"for {test_id} step {step_index}"
            )
        marker_rel = mats.subjects.get(marker_subject)
        seed_rel = mats.subjects.get(seed_subject)
        if marker_rel is None or seed_rel is None:
            raise SystemExit(
                f"FAIL: bdg: PREPARE_LATEST_BUNDLE_900 references unknown subjects for {test_id}"
            )
        ws_marker = ws_repo / marker_rel
        ws_marker.parent.mkdir(parents=True, exist_ok=True)
        ws_marker.write_text("badguys commit marker\ntest\n", encoding="utf-8")
        with contextlib.suppress(FileNotFoundError):
            (ws_repo / seed_rel).unlink()
        patch_txt = (
            f"diff --git a/{marker_rel} b/{marker_rel}\n"
            "index 1111111..2222222 100644\n"
            f"--- a/{marker_rel}\n"
            f"+++ b/{marker_rel}\n"
            "@@ -1,2 +1,2 @@\n"
            " badguys commit marker\n"
            "-test\n"
            f"+{stamp}\n"
        )
        unsucc_dir = patches_dir / "unsuccessful"
        unsucc_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = unsucc_dir / f"issue_{issue}__badguys_latest_bundle__{stamp}.zip"
        inner_name = f"issue_{issue}__badguys_fix_marker__{stamp}.patch"
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            info = zipfile.ZipInfo(inner_name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, patch_txt.encode("utf-8"))
        bundle_path.write_bytes(buf.getvalue())
        return StepResult(rc=0, stdout=None, stderr=None, value=str(bundle_path))

    raise SystemExit(f"FAIL: bdg: unsupported op: {op}")
