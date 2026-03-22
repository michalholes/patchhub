from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from badguys import run_suite
from badguys.run_suite import _make_cfg


def _write_config(repo_root: Path, body: str) -> Path:
    path = repo_root / "badguys" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_suite_jail_defaults_to_true_when_key_missing(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """[suite]
issue_id = "661"

[lock]

[runner]
""",
    )
    cfg = _make_cfg(tmp_path, config_path.relative_to(tmp_path), None, None, None, None, None)
    assert cfg.suite_jail is True


def test_suite_jail_cli_force_on_overrides_config_false(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """[suite]
issue_id = "661"
suite_jail = false

[lock]

[runner]
""",
    )
    cfg = _make_cfg(tmp_path, config_path.relative_to(tmp_path), None, None, None, None, True)
    assert cfg.suite_jail is True


def test_suite_jail_cli_force_off_overrides_config_true(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """[suite]
issue_id = "661"
suite_jail = true

[lock]

[runner]
""",
    )
    cfg = _make_cfg(tmp_path, config_path.relative_to(tmp_path), None, None, None, None, False)
    assert cfg.suite_jail is False


def test_main_passes_suite_jail_cli_override(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool | None] = []

    def _fake_make_cfg(
        repo_root: Path,
        config_path: Path,
        cli_runner_verbosity: str | None,
        cli_console_verbosity: str | None,
        cli_log_verbosity: str | None,
        cli_per_run_logs_post_run: str | None,
        cli_suite_jail: bool | None,
    ) -> SimpleNamespace:
        seen.append(cli_suite_jail)
        return SimpleNamespace(
            lock_path=repo_root / "patches" / "badguys.lock",
            lock_ttl_seconds=3600,
            lock_on_conflict="fail",
            suite_jail=bool(cli_suite_jail),
        )

    monkeypatch.setattr(run_suite, "_make_cfg", _fake_make_cfg)
    monkeypatch.setattr("badguys._util.acquire_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr("badguys._util.release_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_suite, "_outer_suite_run", lambda *args, **kwargs: 0)

    assert run_suite.main(["--suite-jail"]) == 0
    assert run_suite.main(["--no-suite-jail"]) == 0
    assert seen == [True, False]


def test_main_rejects_conflicting_suite_jail_flags() -> None:
    with pytest.raises(SystemExit):
        run_suite.main(["--suite-jail", "--no-suite-jail"])
