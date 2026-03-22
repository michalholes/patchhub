#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
import shutil
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from badguys.bdg_ops_ipc import runner_socket_name


@dataclass(frozen=True)
class SuiteCfg:
    repo_root: Path
    config_path: str
    issue_id: str
    runner_cmd: list[str]
    patches_dir: Path
    logs_dir: Path
    central_log_pattern: str
    lock_path: Path
    lock_ttl_seconds: int
    lock_on_conflict: str
    console_verbosity: str
    log_verbosity: str
    per_run_logs_post_run: str
    full_runner_tests: list[str]
    copy_runner_log: bool
    write_subprocess_stdio: bool

    def central_log_path(self, run_id: str) -> Path:
        rel = self.central_log_pattern.format(run_id=run_id)
        return self.repo_root / Path(rel)


@dataclass
class Ctx:
    repo_root: Path
    run_id: str
    central_log: Path
    cfg: SuiteCfg
    console_verbosity: str
    log_verbosity: str

    def test_dir(self, test_id: str) -> Path:
        return self.cfg.logs_dir / test_id

    def test_log_path(self, test_id: str) -> Path:
        return self.test_dir(test_id) / "badguys.test.jsonl"


def _load_config(repo_root: Path, config_path: Path) -> dict:
    p = repo_root / config_path
    if not p.exists():
        return {}
    return tomllib.loads(p.read_text(encoding="utf-8"))


def _resolve_value(cli: str | None, cfg_val: str | None, default: str) -> str:
    if cli is not None:
        return str(cli)
    if cfg_val is not None:
        return str(cfg_val)
    return default


def _make_cfg(
    repo_root: Path,
    config_path: Path,
    cli_runner_verbosity: str | None,
    cli_console_verbosity: str | None,
    cli_log_verbosity: str | None,
    cli_per_run_logs_post_run: str | None,
) -> SuiteCfg:
    raw = _load_config(repo_root, config_path)
    suite = raw.get("suite", {})
    lock = raw.get("lock", {})
    runner = raw.get("runner", {})

    issue_id = str(suite.get("issue_id", "666"))
    runner_cmd = [str(x) for x in suite.get("runner_cmd", ["python3", "scripts/am_patch.py"])]

    full_runner_tests_raw = runner.get("full_runner_tests", [])
    if full_runner_tests_raw is None:
        full_runner_tests_raw = []
    if not (
        isinstance(full_runner_tests_raw, list)
        and all(isinstance(x, str) for x in full_runner_tests_raw)
    ):
        raise SystemExit("FAIL: runner.full_runner_tests must be list[str]")
    full_runner_tests = [str(x) for x in full_runner_tests_raw]

    env_py = os.environ.get("AM_PATCH_BADGUYS_RUNNER_PYTHON")
    if env_py and runner_cmd:
        head = str(runner_cmd[0])
        if (
            head in {"python", "python3", "/usr/bin/python3", "/usr/bin/python"}
            or head.endswith("/python3")
            or head.endswith("/python")
        ):
            runner_cmd[0] = str(env_py)

    runner_verbosity = _resolve_value(
        cli_runner_verbosity,
        suite.get("runner_verbosity"),
        "quiet",
    ).strip()
    if runner_verbosity:
        runner_cmd = runner_cmd + [f"--verbosity={runner_verbosity}"]

    runner_cmd = runner_cmd + [
        "--ipc-socket-mode=patch_dir",
        "--ipc-socket-name-template=am_patch_ipc_{issue}.sock",
    ]

    console_verbosity = _resolve_value(
        cli_console_verbosity,
        suite.get("console_verbosity"),
        "normal",
    ).strip()
    if console_verbosity not in {"debug", "verbose", "normal", "quiet"}:
        raise SystemExit(f"FAIL: invalid BadGuys console verbosity: {console_verbosity!r}")

    log_verbosity = _resolve_value(cli_log_verbosity, suite.get("log_verbosity"), "normal").strip()
    if log_verbosity not in {"debug", "verbose", "normal", "quiet"}:
        raise SystemExit(f"FAIL: invalid BadGuys log verbosity: {log_verbosity!r}")

    per_run_logs_post_run = _resolve_value(
        cli_per_run_logs_post_run,
        suite.get("per_run_logs_post_run"),
        "keep_all",
    ).strip()
    if per_run_logs_post_run not in {"delete_all", "keep_all", "delete_successful"}:
        raise SystemExit(
            "FAIL: invalid per_run_logs_post_run: "
            f"{per_run_logs_post_run!r} (expected delete_all|keep_all|delete_successful)"
        )

    patches_dir = repo_root / str(suite.get("patches_dir", "patches"))
    logs_dir = repo_root / str(suite.get("logs_dir", "patches/badguys_logs"))
    central_log_pattern = str(suite.get("central_log_pattern", "patches/badguys_{run_id}.log"))

    copy_runner_log = suite.get("copy_runner_log", False)
    if not isinstance(copy_runner_log, bool):
        raise SystemExit("FAIL: suite.copy_runner_log must be bool")

    write_subprocess_stdio = suite.get("write_subprocess_stdio", False)
    if not isinstance(write_subprocess_stdio, bool):
        raise SystemExit("FAIL: suite.write_subprocess_stdio must be bool")

    lock_path = repo_root / str(lock.get("path", "patches/badguys.lock"))
    lock_ttl_seconds = int(lock.get("ttl_seconds", 3600))
    lock_on_conflict = str(lock.get("on_conflict", "fail"))

    return SuiteCfg(
        repo_root=repo_root,
        config_path=str(config_path),
        issue_id=issue_id,
        runner_cmd=runner_cmd,
        patches_dir=patches_dir,
        logs_dir=logs_dir,
        central_log_pattern=central_log_pattern,
        lock_path=lock_path,
        lock_ttl_seconds=lock_ttl_seconds,
        lock_on_conflict=lock_on_conflict,
        console_verbosity=console_verbosity,
        log_verbosity=log_verbosity,
        per_run_logs_post_run=per_run_logs_post_run,
        full_runner_tests=full_runner_tests,
        copy_runner_log=bool(copy_runner_log),
        write_subprocess_stdio=bool(write_subprocess_stdio),
    )


_VERBOSITY_ORDER = {"quiet": 0, "normal": 1, "verbose": 2, "debug": 3}


def _want(verbosity: str, level: str) -> bool:
    return _VERBOSITY_ORDER[verbosity] >= _VERBOSITY_ORDER[level]


def _ensure_repo_root_in_syspath(repo_root: Path) -> None:
    s = str(repo_root)
    if sys.path and sys.path[0] == s:
        return
    if s not in sys.path:
        sys.path.insert(0, s)


def _json_line(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n"


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(_json_line(obj))


def _init_logs(cfg: SuiteCfg, run_id: str) -> Path:
    logs_dir = cfg.logs_dir
    if logs_dir.exists():
        shutil.rmtree(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    central = cfg.central_log_path(run_id)
    central.parent.mkdir(parents=True, exist_ok=True)
    central.write_text(_json_line({"type": "badguys_run", "run_id": run_id}), encoding="utf-8")
    return central


def _ensure_test_artifacts(ctx: Ctx, test_id: str) -> None:
    d = ctx.test_dir(test_id)
    d.mkdir(parents=True, exist_ok=True)
    p = ctx.test_log_path(test_id)
    if p.exists():
        return
    p.write_text(
        _json_line({"type": "badguys_test", "run_id": ctx.run_id, "test_id": test_id}),
        encoding="utf-8",
    )


def _log(ctx: Ctx, *, level: str, test_id: str | None, obj: dict[str, Any]) -> None:
    if not _want(ctx.log_verbosity, level):
        return

    _append_jsonl(ctx.central_log, obj)
    if test_id is not None:
        _ensure_test_artifacts(ctx, test_id)
        _append_jsonl(ctx.test_log_path(test_id), obj)


def _console(ctx: Ctx, *, level: str, text: str) -> None:
    if not _want(ctx.console_verbosity, level):
        return
    sys.stdout.write(text)
    sys.stdout.flush()


def _post_run_cleanup_logs(cfg: SuiteCfg, per_test_ok: dict[str, bool]) -> None:
    mode = cfg.per_run_logs_post_run
    logs_dir = cfg.logs_dir
    if mode == "keep_all":
        return
    if mode == "delete_all":
        if logs_dir.exists():
            shutil.rmtree(logs_dir)
        return

    for test_id, ok in per_test_ok.items():
        if not ok:
            continue
        d = logs_dir / test_id
        if d.exists():
            shutil.rmtree(d)


def _cleanup_issue_artifacts(ctx: Ctx, *, issue_id: str, test_id: str | None) -> None:
    repo_root = ctx.repo_root

    def _rm_tree(p: Path) -> None:
        shutil.rmtree(p, ignore_errors=True)

    def _rm_glob(pattern: str) -> None:
        for path_str in glob.glob(pattern):
            p = Path(path_str)
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()

    ws = repo_root / "patches" / "workspaces" / f"issue_{issue_id}"
    _log(ctx, level="verbose", test_id=test_id, obj={"type": "cleanup", "path": str(ws)})
    _rm_tree(ws)

    logs_dir = repo_root / "patches" / "logs"
    issue_logs_pat = f"issue_{issue_id}*"
    if logs_dir.exists():
        for p in logs_dir.glob(issue_logs_pat):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()

    for pat in (
        str(repo_root / "patches" / "successful" / f"issue_{issue_id}*"),
        str(repo_root / "patches" / "unsuccessful" / f"issue_{issue_id}*"),
        str(repo_root / "patches" / f"patched_issue{issue_id}_*.zip"),
        str(repo_root / "patches" / f"issue_{issue_id}__bdg__*"),
    ):
        _log(
            ctx,
            level="verbose",
            test_id=test_id,
            obj={"type": "cleanup_glob", "pattern": pat},
        )
        _rm_glob(pat)

    socket_name = runner_socket_name(argv=ctx.cfg.runner_cmd, issue_id=issue_id)
    socket_path = ctx.cfg.patches_dir / socket_name
    _log(
        ctx,
        level="verbose",
        test_id=test_id,
        obj={"type": "cleanup", "path": str(socket_path)},
    )
    with contextlib.suppress(FileNotFoundError):
        socket_path.unlink()


def _load_eval_rules(repo_root: Path, config_path: Path) -> dict:
    raw = tomllib.loads((repo_root / config_path).read_text(encoding="utf-8"))
    return raw.get("evaluation", {})


def _rules_for_step(evaluation: dict, *, test_id: str, step_index: int) -> dict:
    tests = evaluation.get("tests", {})
    if not isinstance(tests, dict):
        return {}
    t = tests.get(test_id, {})
    if not isinstance(t, dict):
        return {}
    steps = t.get("steps", {})
    if not isinstance(steps, dict):
        return {}
    s = steps.get(str(step_index)) if str(step_index) in steps else steps.get(step_index)
    if not isinstance(s, dict):
        return {}
    return s


def _run_test_plan(test, ctx: Ctx) -> bool:
    from badguys.bdg_evaluator import StepResult, evaluate_step
    from badguys.bdg_executor import execute_bdg_step
    from badguys.bdg_loader import BdgTest
    from badguys.bdg_materializer import materialize_assets
    from badguys.bdg_ops_ipc import has_pending_ipc_plans
    from badguys.bdg_subst import make_subst_ctx

    name = getattr(test, "name", "(unknown)")
    evaluation = _load_eval_rules(ctx.repo_root, Path(ctx.cfg.config_path))
    strict = bool(evaluation.get("strict_coverage", True))

    try:
        obj = test.run(ctx)
    except SystemExit as e:
        _log(ctx, level="quiet", test_id=name, obj={"type": "test_error", "msg": str(e)})
        return False

    if not isinstance(obj, BdgTest):
        raise SystemExit(f"FAIL: test {name} returned unsupported type: {type(obj).__name__}")

    bdg = obj
    _ensure_test_artifacts(ctx, bdg.test_id)
    _log(
        ctx,
        level="quiet",
        test_id=bdg.test_id,
        obj={"type": "test_begin", "test_id": bdg.test_id},
    )

    subst = make_subst_ctx(issue_id=ctx.cfg.issue_id)
    mats = materialize_assets(
        repo_root=ctx.repo_root,
        config_path=Path(ctx.cfg.config_path),
        subst=subst,
        bdg=bdg,
    )

    ok = True
    prior: dict[int, StepResult] = {}

    step_runner_cfg: dict[str, object] = {
        "patches_dir": ctx.cfg.patches_dir,
        "artifacts_dir": ctx.test_dir(bdg.test_id),
        "copy_runner_log": ctx.cfg.copy_runner_log,
        "write_subprocess_stdio": ctx.cfg.write_subprocess_stdio,
        "console_verbosity": ctx.console_verbosity,
    }

    for idx, step in enumerate(bdg.steps):
        r = execute_bdg_step(
            repo_root=ctx.repo_root,
            config_path=Path(ctx.cfg.config_path),
            cfg_runner_cmd=list(ctx.cfg.runner_cmd),
            subst=subst,
            full_runner_tests=set(ctx.cfg.full_runner_tests),
            step=step,
            mats=mats,
            test_id=bdg.test_id,
            step_index=int(idx),
            step_runner_cfg=step_runner_cfg,
        )

        rules = _rules_for_step(evaluation, test_id=bdg.test_id, step_index=idx)
        if strict and not rules:
            ok = False
            _log(
                ctx,
                level="quiet",
                test_id=bdg.test_id,
                obj={
                    "type": "fail",
                    "reason": "missing_evaluation_rules",
                    "step_index": int(idx),
                },
            )
        else:
            if step.op == "RUN_RUNNER":
                for k in rules:
                    if k.startswith("stdout_") or k.startswith("stderr_"):
                        ok = False
                        _log(
                            ctx,
                            level="quiet",
                            test_id=bdg.test_id,
                            obj={
                                "type": "fail",
                                "reason": "forbidden_evaluation_keys_for_runner",
                                "step_index": int(idx),
                                "key": str(k),
                            },
                        )
                        rules = {}
                        break

            if rules:
                passed, msg = evaluate_step(
                    rules=rules,
                    result=r,
                    prior=prior,
                    test_id=bdg.test_id,
                    step_index=idx,
                )
                if not passed:
                    ok = False
                    _log(
                        ctx,
                        level="quiet",
                        test_id=bdg.test_id,
                        obj={
                            "type": "step_fail",
                            "step_index": int(idx),
                            "msg": str(msg),
                        },
                    )

        step_obj: dict[str, Any] = {
            "type": "step",
            "step_index": int(idx),
            "op": str(step.op),
            "rc": r.rc,
        }
        if step.op == "RUN_RUNNER":
            step_obj["ipc_stream"] = f"runner.ipc.step{int(idx)}.jsonl"
            res_path = ctx.test_dir(bdg.test_id) / "runner.result.json"
            if res_path.exists():
                step_obj["runner_result"] = res_path.name
            jsonl_path = ctx.test_dir(bdg.test_id) / "runner.log.jsonl"
            if jsonl_path.exists():
                step_obj["runner_jsonl"] = jsonl_path.name

        _log(ctx, level="normal", test_id=bdg.test_id, obj=step_obj)

        prior[idx] = r

    if has_pending_ipc_plans(step_runner_cfg):
        ok = False
        _log(
            ctx,
            level="quiet",
            test_id=bdg.test_id,
            obj={"type": "fail", "reason": "unused_ipc_send_command_steps"},
        )

    _log(
        ctx,
        level="quiet",
        test_id=bdg.test_id,
        obj={"type": "test_end", "test_id": bdg.test_id, "ok": bool(ok)},
    )
    return ok


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python3 badguys/badguys.py")
    ap.add_argument("--config", default="badguys/config.toml", help="Config path (repo-relative)")
    ap.add_argument(
        "--commit-limit",
        type=int,
        default=None,
        help="Override commit_limit from config",
    )
    ap.add_argument(
        "--runner-verbosity",
        default=None,
        choices=["debug", "verbose", "normal", "quiet"],
        help="Override runner verbosity (passed as --verbosity=<mode>)",
    )
    vg = ap.add_mutually_exclusive_group()
    vg.add_argument("-q", dest="console_verbosity", action="store_const", const="quiet")
    vg.add_argument("-n", dest="console_verbosity", action="store_const", const="normal")
    vg.add_argument("-v", dest="console_verbosity", action="store_const", const="verbose")
    vg.add_argument("-d", dest="console_verbosity", action="store_const", const="debug")
    ap.add_argument(
        "--log-verbosity",
        default=None,
        choices=["debug", "verbose", "normal", "quiet"],
        help="BadGuys log verbosity (central + per-test logs)",
    )
    ap.add_argument(
        "--per-run-logs-post-run",
        default=None,
        choices=["delete_all", "keep_all", "delete_successful"],
        help="Post-run per-test artifact cleanup policy",
    )
    ap.add_argument(
        "--include",
        action="append",
        default=[],
        help="Run only named tests (repeatable)",
    )
    ap.add_argument("--exclude", action="append", default=[], help="Skip named tests (repeatable)")
    ap.add_argument("--list-tests", action="store_true", help="List discovered tests and exit")
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    _ensure_repo_root_in_syspath(repo_root)

    cfg = _make_cfg(
        repo_root,
        Path(args.config),
        args.runner_verbosity,
        args.console_verbosity,
        args.log_verbosity,
        args.per_run_logs_post_run,
    )
    run_id = time.strftime("%Y%m%d_%H%M%S")

    from badguys._util import (
        acquire_lock,
        fail_commit_limit,
        format_result_line,
        release_lock,
    )
    from badguys.discovery import discover_tests

    acquire_lock(
        repo_root,
        path=cfg.lock_path,
        ttl_seconds=cfg.lock_ttl_seconds,
        on_conflict=cfg.lock_on_conflict,
    )

    try:
        central_log = _init_logs(cfg, run_id)

        tests = discover_tests(
            repo_root=repo_root,
            config_path=Path(args.config),
            cli_commit_limit=args.commit_limit,
            cli_include=list(args.include),
            cli_exclude=list(args.exclude),
        )

        all_test_ids = {
            t.name
            for t in discover_tests(
                repo_root=repo_root,
                config_path=Path(args.config),
                cli_commit_limit=args.commit_limit,
                cli_include=[],
                cli_exclude=[],
            )
        }
        unknown = sorted(set(cfg.full_runner_tests).difference(all_test_ids))
        if unknown:
            joined = ", ".join(unknown)
            raise SystemExit(
                f"FAIL: runner.full_runner_tests references unknown test_id(s): {joined}"
            )

        if args.list_tests:
            for t in tests:
                print(t.name)
            return 0

        ctx = Ctx(
            repo_root=repo_root,
            run_id=run_id,
            central_log=central_log,
            cfg=cfg,
            console_verbosity=cfg.console_verbosity,
            log_verbosity=cfg.log_verbosity,
        )

        if ctx.log_verbosity == "debug":
            _log(
                ctx,
                level="debug",
                test_id=None,
                obj={
                    "type": "debug_config",
                    "config_path": args.config,
                    "console_verbosity": cfg.console_verbosity,
                    "log_verbosity": cfg.log_verbosity,
                    "runner_cmd": " ".join(cfg.runner_cmd),
                    "issue_id": cfg.issue_id,
                    "per_run_logs_post_run": cfg.per_run_logs_post_run,
                },
            )

        commit_limit = int(getattr(tests, "commit_limit", 1))
        commit_tests = [t for t in tests if bool(getattr(t, "makes_commit", False))]
        if len(commit_tests) > commit_limit:
            fail_commit_limit(central_log, commit_limit, commit_tests)

        ok_all = True
        interrupted = False
        per_test_ok: dict[str, bool] = {}

        for idx, t in enumerate(tests):
            try:
                _cleanup_issue_artifacts(
                    ctx,
                    issue_id=cfg.issue_id,
                    test_id=getattr(t, "name", None),
                )

                ok = False
                try:
                    ok = _run_test_plan(t, ctx)
                finally:
                    _cleanup_issue_artifacts(
                        ctx,
                        issue_id=cfg.issue_id,
                        test_id=getattr(t, "name", None),
                    )

                per_test_ok[t.name] = bool(ok)

                if ctx.console_verbosity in {"normal", "verbose", "debug"}:
                    _console(ctx, level="normal", text=format_result_line(t.name, ok))

                if not ok:
                    ok_all = False
                    if idx == 0 and bool(getattr(tests, "abort_on_guard_fail", False)):
                        break

            except KeyboardInterrupt:
                interrupted = True
                ok_all = False
                break

        status = "OK" if ok_all else "FAIL"
        passed = sum(1 for ok in per_test_ok.values() if ok)
        failed = sum(1 for ok in per_test_ok.values() if not ok)

        if ctx.console_verbosity == "quiet":
            summary = f"BadGuys summary: {status}\n"
        else:
            summary = f"BadGuys summary: {status} passed={passed} failed={failed}\n"
        _console(ctx, level="quiet", text=summary)

        _log(
            ctx,
            level="quiet",
            test_id=None,
            obj={
                "type": "badguys_summary",
                "status": status,
                "passed": passed,
                "failed": failed,
            },
        )

        _post_run_cleanup_logs(cfg, per_test_ok)

        if interrupted:
            return 130
        return 0 if ok_all else 1

    finally:
        release_lock(repo_root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
