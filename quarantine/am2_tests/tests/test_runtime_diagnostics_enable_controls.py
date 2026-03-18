from __future__ import annotations

from pathlib import Path

import pytest

from audiomason.core.config import ConfigResolver
from audiomason.core.diagnostics import is_diagnostics_enabled
from audiomason.core.logging import VerbosityLevel, set_verbosity


def _write_user_config(path: Path, *, enabled: bool) -> None:
    text = "diagnostics:\n  enabled: %s\n" % ("true" if enabled else "false")
    path.write_text(text, encoding="utf-8")


def _resolver_with_user_config(
    tmp_path: Path, *, cli_args: dict | None, enabled: bool
) -> ConfigResolver:
    user_cfg = tmp_path / "user_config.yaml"
    sys_cfg = tmp_path / "system_config.yaml"
    _write_user_config(user_cfg, enabled=enabled)
    sys_cfg.write_text("{}\n", encoding="utf-8")
    return ConfigResolver(
        cli_args=cli_args,
        user_config_path=user_cfg,
        system_config_path=sys_cfg,
    )


def test_cli_true_overrides_env_and_config_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_verbosity(VerbosityLevel.NORMAL)
    monkeypatch.setenv("AUDIOMASON_DIAGNOSTICS_ENABLED", "0")

    resolver = _resolver_with_user_config(
        tmp_path,
        cli_args={"diagnostics": {"enabled": True}},
        enabled=False,
    )

    assert is_diagnostics_enabled(resolver) is True


def test_cli_false_overrides_env_and_config_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_verbosity(VerbosityLevel.NORMAL)
    monkeypatch.setenv("AUDIOMASON_DIAGNOSTICS_ENABLED", "1")

    resolver = _resolver_with_user_config(
        tmp_path,
        cli_args={"diagnostics": {"enabled": False}},
        enabled=True,
    )

    assert is_diagnostics_enabled(resolver) is False


def test_env_overrides_config_when_cli_not_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_verbosity(VerbosityLevel.NORMAL)
    monkeypatch.setenv("AUDIOMASON_DIAGNOSTICS_ENABLED", "1")

    resolver = _resolver_with_user_config(
        tmp_path,
        cli_args=None,
        enabled=False,
    )

    assert is_diagnostics_enabled(resolver) is True


def test_unknown_env_value_disables_and_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_verbosity(VerbosityLevel.NORMAL)
    monkeypatch.setenv("AUDIOMASON_DIAGNOSTICS_ENABLED", "maybe")

    resolver = _resolver_with_user_config(
        tmp_path,
        cli_args=None,
        enabled=True,
    )

    assert is_diagnostics_enabled(resolver) is False

    out = capsys.readouterr().out
    assert "AUDIOMASON_DIAGNOSTICS_ENABLED" in out
    assert "treating as disabled" in out
