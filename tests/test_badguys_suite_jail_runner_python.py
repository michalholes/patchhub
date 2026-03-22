from __future__ import annotations

from pathlib import Path

from badguys import run_suite

ISSUE_ID = "664"


def _write_config(repo_root: Path, suite_jail: bool) -> Path:
    config_path = repo_root / "badguys" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "[suite]",
                f'issue_id = "{ISSUE_ID}"',
                f"suite_jail = {'true' if suite_jail else 'false'}",
                'runner_cmd = ["python3", "scripts/am_patch.py"]',
                'logs_dir = "patches/badguys_logs"',
                'central_log_pattern = "patches/badguys_{run_id}.log"',
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def test_suite_jail_visible_path_maps_repo_local_python_to_repo_mount(tmp_path: Path) -> None:
    python_path = tmp_path / ".venv" / "bin" / "python"
    assert (
        run_suite._suite_jail_visible_path(
            repo_root=tmp_path,
            value=str(python_path),
        )
        == "/repo/.venv/bin/python"
    )


def test_outer_suite_run_propagates_jail_visible_python_for_inner_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_config(tmp_path, suite_jail=True)
    cfg = run_suite._make_cfg(
        tmp_path,
        config_path.relative_to(tmp_path),
        None,
        None,
        None,
        None,
        None,
    )

    seen: dict[str, object] = {}
    jail_python = "/repo/.venv/bin/python"

    monkeypatch.setattr(run_suite, "require_bwrap", lambda: "/usr/bin/bwrap")
    monkeypatch.setattr(run_suite.sys, "executable", str(tmp_path / ".venv" / "bin" / "python"))
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
        env,
    ) -> int:
        seen["argv"] = list(argv)
        seen["env"] = dict(env)
        return 0

    monkeypatch.setattr(run_suite, "run_in_suite_jail", _fake_run_in_suite_jail)
    monkeypatch.setattr(run_suite, "teardown_suite_jail", lambda host_repo_root, issue_id: None)

    args = type(
        "Args",
        (),
        {
            "config": str(config_path.relative_to(tmp_path)),
            "commit_limit": None,
            "runner_verbosity": None,
            "console_verbosity": None,
            "log_verbosity": None,
            "per_run_logs_post_run": None,
            "suite_jail": True,
            "include": [],
            "exclude": [],
            "list_tests": False,
        },
    )()

    assert run_suite._outer_suite_run(args, cfg, repo_root=tmp_path, run_id="testrun") == 0
    assert seen["argv"] == [
        jail_python,
        "badguys/badguys.py",
        "--config",
        "badguys/config.toml",
        "--suite-jail",
    ]
    assert seen["env"]["AM_PATCH_BADGUYS_RUNNER_PYTHON"] == jail_python

    monkeypatch.setenv("AM_PATCH_BADGUYS_RUNNER_PYTHON", jail_python)
    inner_cfg = run_suite._make_cfg(
        tmp_path,
        config_path.relative_to(tmp_path),
        None,
        None,
        None,
        None,
        None,
    )
    assert inner_cfg.runner_cmd[0] == jail_python
