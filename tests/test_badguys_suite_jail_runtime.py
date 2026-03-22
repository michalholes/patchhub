from __future__ import annotations

from pathlib import Path

from badguys import run_suite
from badguys.run_suite import Ctx, SuiteCfg, _cleanup_issue_artifacts, _make_cfg

ISSUE_ID = "661"


def _write_config(repo_root: Path, suite_jail: bool) -> Path:
    path = repo_root / "badguys" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[suite]",
                f'issue_id = "{ISSUE_ID}"',
                f"suite_jail = {'true' if suite_jail else 'false'}",
                'logs_dir = "patches/badguys_logs"',
                'central_log_pattern = "patches/badguys_{run_id}.log"',
                "",
                "[lock]",
                "",
                "[runner]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _make_ctx(repo_root: Path) -> Ctx:
    patches_dir = repo_root / "patches"
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
        central_log=patches_dir / "badguys_test.log",
        cfg=cfg,
        console_verbosity="quiet",
        log_verbosity="quiet",
    )


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def test_jail_mode_tears_down_only_after_whole_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_config(tmp_path, suite_jail=True)
    cfg = _make_cfg(
        tmp_path,
        config_path.relative_to(tmp_path),
        None,
        None,
        None,
        None,
        None,
    )

    events: list[tuple[str, str]] = []

    monkeypatch.setattr(run_suite, "require_bwrap", lambda: "/usr/bin/bwrap")
    monkeypatch.setattr(
        run_suite.suite_jail_runtime,
        "external_bind_paths",
        lambda *, repo_root: [],
    )

    def _fake_prepare_suite_jail(
        *,
        host_repo_root: Path,
        issue_id: str,
        host_bind_paths,
        host_external_bind_paths,
    ):
        jail_root = host_repo_root / "patches" / "badguys_suite_jail" / f"issue_{issue_id}"
        repo_root = jail_root / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        return type("SuiteJail", (), {"root": jail_root, "repo_root": repo_root})()

    def _fake_run_in_suite_jail(
        *,
        host_repo_root: Path,
        jail_repo_root: Path,
        argv,
        host_bind_paths,
        host_external_bind_paths,
        env,
    ):
        assert host_external_bind_paths == []
        events.append(("run_start", str(jail_repo_root.parent.exists())))
        _cleanup_issue_artifacts(_make_ctx(jail_repo_root), issue_id=ISSUE_ID, test_id="probe")
        events.append(("after_cleanup", str(jail_repo_root.parent.exists())))
        return 0

    def _fake_teardown_suite_jail(host_repo_root: Path, issue_id: str) -> None:
        jail_root = host_repo_root / "patches" / "badguys_suite_jail" / f"issue_{issue_id}"
        events.append(("before_teardown", str(jail_root.exists())))
        if jail_root.exists():
            import shutil

            shutil.rmtree(jail_root)
        events.append(("after_teardown", str(jail_root.exists())))

    monkeypatch.setattr(run_suite, "prepare_suite_jail", _fake_prepare_suite_jail)
    monkeypatch.setattr(run_suite, "run_in_suite_jail", _fake_run_in_suite_jail)
    monkeypatch.setattr(run_suite, "teardown_suite_jail", _fake_teardown_suite_jail)

    args = type(
        "Args",
        (),
        {
            "config": str(config_path.relative_to(tmp_path)),
            "commit_limit": None,
            "include": [],
            "exclude": [],
            "list_tests": False,
        },
    )()

    assert run_suite._outer_suite_run(args, cfg, repo_root=tmp_path, run_id="testrun") == 0
    assert events == [
        ("run_start", "True"),
        ("after_cleanup", "True"),
        ("before_teardown", "True"),
        ("after_teardown", "False"),
    ]


def test_jail_mode_live_host_patches_keeps_only_logs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_config(tmp_path, suite_jail=True)
    cfg = _make_cfg(
        tmp_path,
        config_path.relative_to(tmp_path),
        None,
        None,
        None,
        None,
        None,
    )

    monkeypatch.setattr(run_suite, "require_bwrap", lambda: "/usr/bin/bwrap")
    monkeypatch.setattr(
        run_suite.suite_jail_runtime,
        "external_bind_paths",
        lambda *, repo_root: [],
    )

    def _fake_prepare_suite_jail(
        *,
        host_repo_root: Path,
        issue_id: str,
        host_bind_paths,
        host_external_bind_paths,
    ):
        jail_root = host_repo_root / "patches" / "badguys_suite_jail" / f"issue_{issue_id}"
        repo_root = jail_root / "repo"
        (repo_root / "patches").mkdir(parents=True, exist_ok=True)
        return type("SuiteJail", (), {"root": jail_root, "repo_root": repo_root})()

    def _fake_run_in_suite_jail(
        *,
        host_repo_root: Path,
        jail_repo_root: Path,
        argv,
        host_bind_paths,
        host_external_bind_paths,
        env,
    ):
        assert host_bind_paths == [
            host_repo_root / "patches" / "badguys_logs",
            host_repo_root / "patches" / "badguys_testrun.log",
        ]
        assert host_external_bind_paths == []
        _touch(
            jail_repo_root
            / "patches"
            / "badguys_artifacts"
            / f"issue_{ISSUE_ID}"
            / "probe"
            / "artifact.txt"
        )
        _touch(jail_repo_root / "patches" / f"issue_{ISSUE_ID}__bdg__probe.patch")
        return 0

    def _fake_teardown_suite_jail(host_repo_root: Path, issue_id: str) -> None:
        import shutil

        shutil.rmtree(
            host_repo_root / "patches" / "badguys_suite_jail" / f"issue_{issue_id}",
            ignore_errors=True,
        )

    monkeypatch.setattr(run_suite, "prepare_suite_jail", _fake_prepare_suite_jail)
    monkeypatch.setattr(run_suite, "run_in_suite_jail", _fake_run_in_suite_jail)
    monkeypatch.setattr(run_suite, "teardown_suite_jail", _fake_teardown_suite_jail)

    args = type(
        "Args",
        (),
        {
            "config": str(config_path.relative_to(tmp_path)),
            "commit_limit": None,
            "include": [],
            "exclude": [],
            "list_tests": False,
        },
    )()

    assert run_suite._outer_suite_run(args, cfg, repo_root=tmp_path, run_id="testrun") == 0
    patches_dir = tmp_path / "patches"
    assert (patches_dir / "badguys_testrun.log").exists()
    assert (patches_dir / "badguys_logs").exists()
    assert not (patches_dir / "badguys_artifacts" / f"issue_{ISSUE_ID}").exists()
    assert not (patches_dir / f"issue_{ISSUE_ID}__bdg__probe.patch").exists()
    assert not (patches_dir / "badguys_suite_jail" / f"issue_{ISSUE_ID}").exists()


def test_jail_mode_uses_current_call_args_not_ambient_sys_argv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_config(tmp_path, suite_jail=True)
    cfg = _make_cfg(
        tmp_path,
        config_path.relative_to(tmp_path),
        None,
        None,
        None,
        None,
        None,
    )

    seen: list[str] = []

    monkeypatch.setattr(run_suite, "require_bwrap", lambda: "/usr/bin/bwrap")
    monkeypatch.setattr(
        run_suite.suite_jail_runtime,
        "external_bind_paths",
        lambda *, repo_root: [],
    )
    monkeypatch.setattr(
        run_suite,
        "prepare_suite_jail",
        lambda **kwargs: type(
            "SuiteJail",
            (),
            {
                "root": tmp_path / "patches" / "badguys_suite_jail" / f"issue_{ISSUE_ID}",
                "repo_root": (
                    tmp_path / "patches" / "badguys_suite_jail" / f"issue_{ISSUE_ID}" / "repo"
                ),
            },
        )(),
    )

    def _fake_run_in_suite_jail(
        *,
        host_repo_root: Path,
        jail_repo_root: Path,
        argv,
        host_bind_paths,
        host_external_bind_paths,
        env,
    ):
        assert host_external_bind_paths == []
        seen[:] = list(argv)
        return 0

    monkeypatch.setattr(run_suite, "run_in_suite_jail", _fake_run_in_suite_jail)
    monkeypatch.setattr(run_suite, "teardown_suite_jail", lambda host_repo_root, issue_id: None)
    monkeypatch.setattr(
        run_suite.sys,
        "argv",
        ["ambient.py", "--config", "ambient.toml", "--exclude", "ambient_only"],
    )

    args = type(
        "Args",
        (),
        {
            "config": str(config_path.relative_to(tmp_path)),
            "commit_limit": 7,
            "runner_verbosity": "debug",
            "console_verbosity": "verbose",
            "log_verbosity": "quiet",
            "per_run_logs_post_run": "delete_successful",
            "suite_jail": True,
            "include": ["keep_me"],
            "exclude": ["drop_me"],
            "list_tests": True,
        },
    )()

    assert run_suite._outer_suite_run(args, cfg, repo_root=tmp_path, run_id="testrun") == 0
    assert seen == [
        run_suite.sys.executable,
        "badguys/badguys.py",
        "--config",
        "badguys/config.toml",
        "--commit-limit",
        "7",
        "--runner-verbosity",
        "debug",
        "-v",
        "--log-verbosity",
        "quiet",
        "--per-run-logs-post-run",
        "delete_successful",
        "--suite-jail",
        "--include",
        "keep_me",
        "--exclude",
        "drop_me",
        "--list-tests",
    ]


def test_non_jail_cleanup_leaves_only_logs_for_current_issue(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    patches_dir = ctx.cfg.patches_dir

    _touch(patches_dir / f"badguys_{ctx.run_id}.log")
    _touch(patches_dir / "badguys_logs" / "probe" / "badguys.test.jsonl")
    _touch(patches_dir / f"issue_{ISSUE_ID}__bdg__probe.patch")
    _touch(patches_dir / "badguys_artifacts" / f"issue_{ISSUE_ID}" / "probe" / "artifact.txt")
    _touch(patches_dir / f"patched_issue{ISSUE_ID}_v01.zip")
    _touch(patches_dir / "successful" / f"issue_{ISSUE_ID}_success.zip")

    _cleanup_issue_artifacts(ctx, issue_id=ISSUE_ID, test_id="probe")

    assert (patches_dir / f"badguys_{ctx.run_id}.log").exists()
    assert (patches_dir / "badguys_logs" / "probe" / "badguys.test.jsonl").exists()
    assert not (patches_dir / f"issue_{ISSUE_ID}__bdg__probe.patch").exists()
    assert not (patches_dir / "badguys_artifacts" / f"issue_{ISSUE_ID}").exists()
    assert not (patches_dir / f"patched_issue{ISSUE_ID}_v01.zip").exists()
    assert not (patches_dir / "successful" / f"issue_{ISSUE_ID}_success.zip").exists()
