from __future__ import annotations

import sys
from pathlib import Path

from badguys import run_suite
from badguys.run_suite import _make_cfg

ISSUE_ID = "664"


def _write_config(repo_root: Path, suite_jail: bool) -> Path:
    path = repo_root / "badguys" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[suite]",
                f'issue_id = "{ISSUE_ID}"',
                f"suite_jail = {'true' if suite_jail else 'false'}",
                'runner_cmd = ["python3", "scripts/am_patch.py"]',
                "",
                "[lock]",
                "",
                "[runner]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_make_cfg_uses_env_runner_python_override(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path, suite_jail=True)
    monkeypatch.setenv("AM_PATCH_BADGUYS_RUNNER_PYTHON", "/tmp/venv/bin/python")

    cfg = _make_cfg(
        tmp_path,
        config_path.relative_to(tmp_path),
        None,
        None,
        None,
        None,
        None,
    )

    assert cfg.runner_cmd[0] == "/tmp/venv/bin/python"
    assert cfg.runner_cmd[1:] == [
        "scripts/am_patch.py",
        "--verbosity=quiet",
        "--ipc-socket-mode=patch_dir",
        "--ipc-socket-name-template=am_patch_ipc_{issue}.sock",
    ]


def test_outer_suite_run_propagates_current_runner_python_into_jail(
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

    seen_env: dict[str, str] = {}

    monkeypatch.setattr(run_suite, "require_bwrap", lambda: "/usr/bin/bwrap")
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
    ):
        seen_env.clear()
        seen_env.update(env)
        return 0

    monkeypatch.setattr(run_suite, "run_in_suite_jail", _fake_run_in_suite_jail)
    monkeypatch.setattr(run_suite, "teardown_suite_jail", lambda host_repo_root, issue_id: None)
    monkeypatch.setattr(run_suite.sys, "executable", "/tmp/venv/bin/python")

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
    assert seen_env["AM_BADGUYS_SUITE_JAIL_INNER"] == "1"
    assert seen_env["AM_BADGUYS_RUN_ID"] == "testrun"
    assert seen_env["AM_PATCH_BADGUYS_RUNNER_PYTHON"] == sys.executable
