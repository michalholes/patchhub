from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from badguys import run_suite
from badguys.run_suite import _make_cfg


def _write_config(repo_root: Path, suite_jail: bool) -> Path:
    path = repo_root / "badguys" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[suite]",
                'issue_id = "661"',
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


def _args(config_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        config=str(config_path),
        commit_limit=None,
        include=[],
        exclude=[],
        list_tests=False,
    )


def test_suite_jail_missing_bwrap_fails_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setenv("AM_PATCH_BWRAP", "bwrap-does-not-exist")

    with pytest.raises(SystemExit, match="bwrap not found"):
        run_suite._outer_suite_run(
            _args(config_path.relative_to(tmp_path)),
            cfg,
            repo_root=tmp_path,
            run_id="testrun",
        )


def test_no_suite_jail_does_not_require_bwrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(tmp_path, suite_jail=False)
    cfg = _make_cfg(
        tmp_path,
        config_path.relative_to(tmp_path),
        None,
        None,
        None,
        None,
        None,
    )
    monkeypatch.setenv("AM_PATCH_BWRAP", "bwrap-does-not-exist")
    monkeypatch.setattr(run_suite, "_run_suite_body", lambda **kwargs: 0)

    assert (
        run_suite._outer_suite_run(
            _args(config_path.relative_to(tmp_path)),
            cfg,
            repo_root=tmp_path,
            run_id="testrun",
        )
        == 0
    )
