"""Unit tests for core.config module."""

from pathlib import Path

import pytest

from audiomason.core.config import ConfigResolver
from audiomason.core.errors import ConfigError


class TestConfigResolver:
    """Tests for ConfigResolver."""

    def test_cli_priority(self, tmp_path):
        """Test that CLI args have highest priority."""
        user_config = tmp_path / "config.yaml"
        user_config.write_text("bitrate: 128k\n")

        resolver = ConfigResolver(
            cli_args={"bitrate": "320k"},
            user_config_path=user_config,
        )

        value, source = resolver.resolve("bitrate")
        assert value == "320k"
        assert source == "cli"

    def test_env_priority(self, tmp_path, monkeypatch):
        """Test that ENV overrides config files."""
        user_config = tmp_path / "config.yaml"
        user_config.write_text("bitrate: 128k\n")

        monkeypatch.setenv("AUDIOMASON_BITRATE", "256k")

        resolver = ConfigResolver(
            cli_args={},
            user_config_path=user_config,
        )

        value, source = resolver.resolve("bitrate")
        assert value == "256k"
        assert source == "env"

    def test_user_config_priority(self, tmp_path):
        """Test that user config overrides system config."""
        user_config = tmp_path / "user.yaml"
        user_config.write_text("bitrate: 128k\n")

        system_config = tmp_path / "system.yaml"
        system_config.write_text("bitrate: 96k\n")

        resolver = ConfigResolver(
            cli_args={},
            user_config_path=user_config,
            system_config_path=system_config,
        )

        value, source = resolver.resolve("bitrate")
        assert value == "128k"
        assert source == "user_config"

    def test_defaults(self, tmp_path):
        """Test that defaults are used when nothing else provides value."""
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent.yaml",
        )

        value, source = resolver.resolve("bitrate")
        assert value == "128k"  # Default
        assert source == "default"

    def test_nested_keys(self, tmp_path):
        """Test nested keys with dot notation."""
        user_config = tmp_path / "config.yaml"
        user_config.write_text(
            """
logging:
  level: debug
  color: true
"""
        )

        resolver = ConfigResolver(
            cli_args={},
            user_config_path=user_config,
        )

        level, source = resolver.resolve("logging.level")
        assert level == "debug"
        assert source == "user_config"

        color, source = resolver.resolve("logging.color")
        assert color is True

    def test_missing_key_raises_error(self, tmp_path):
        """Test that missing key raises ConfigError."""
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            defaults={},
        )

        with pytest.raises(ConfigError, match="not found"):
            resolver.resolve("nonexistent_key")

    def test_false_values_work(self, tmp_path):
        """Test that False values are handled correctly."""
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"loudnorm": False, "split_chapters": False},
        )

        loudnorm, source = resolver.resolve("loudnorm")
        assert loudnorm is False
        assert source == "default"

    def test_resolve_logging_level_default_is_normal(self, tmp_path):
        """If logging.level is missing, resolver returns the explicit default."""
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={},
        )

        assert resolver.resolve_logging_level() == "normal"

    def test_resolve_logging_level_normalizes(self, tmp_path):
        """Resolver normalizes whitespace and case."""
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"logging": {"level": "  DeBuG  "}},
        )

        assert resolver.resolve_logging_level() == "debug"

    def test_resolve_logging_level_invalid_string_raises(self, tmp_path):
        """Unknown verbosity string must raise."""
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"logging": {"level": "loud"}},
        )

        with pytest.raises(ConfigError):
            resolver.resolve_logging_level()

    def test_resolve_logging_level_non_string_raises(self, tmp_path):
        """Non-string verbosity value must raise."""
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"logging": {"level": 123}},
        )

        with pytest.raises(ConfigError):
            resolver.resolve_logging_level()

    def test_resolve_logging_level_empty_string_raises(self, tmp_path):
        """Empty/whitespace verbosity value must raise."""
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"logging": {"level": "   "}},
        )

        with pytest.raises(ConfigError):
            resolver.resolve_logging_level()

    def test_resolve_all(self, tmp_path):
        """Test resolving all keys."""
        resolver = ConfigResolver(
            cli_args={"bitrate": "320k"},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"bitrate": "128k", "loudnorm": False},
        )

        all_config = resolver.resolve_all()

        assert "bitrate" in all_config
        assert all_config["bitrate"].value == "320k"
        assert all_config["bitrate"].source == "cli"

        assert "loudnorm" in all_config
        assert all_config["loudnorm"].value is False

    def test_resolve_logging_policy_default_normal(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={},
        )

        policy = resolver.resolve_logging_policy()

        assert policy.level_name == "normal"
        assert policy.emit_error is True
        assert policy.emit_warning is True
        assert policy.emit_info is True
        assert policy.emit_progress is True
        assert policy.emit_debug is False

    @pytest.mark.parametrize(
        "level, expected",
        [
            ("quiet", (True, True, False, False, False)),
            ("normal", (True, True, True, True, False)),
            ("verbose", (True, True, True, True, True)),
            ("debug", (True, True, True, True, True)),
        ],
    )
    def test_resolve_logging_policy_flags(self, tmp_path, level, expected):
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"logging": {"level": level}},
        )

        policy = resolver.resolve_logging_policy()

        assert policy.level_name == level
        flags = (
            policy.emit_error,
            policy.emit_warning,
            policy.emit_info,
            policy.emit_progress,
            policy.emit_debug,
        )

        assert flags == expected

    def test_resolve_logging_level_alias_verbosity(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"verbosity": "verbose"},
        )

        assert resolver.resolve_logging_level() == "verbose"

    def test_logging_level_canonical_wins_over_alias(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={"verbosity": "debug"},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"logging": {"level": "quiet"}},
        )

        assert resolver.resolve_logging_level() == "quiet"

    def test_resolve_logging_policy_sources_tracks_level(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={"logging": {"level": "debug"}},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={},
        )

        policy = resolver.resolve_logging_policy()

        assert policy.sources["level_name"].value == "debug"
        assert policy.sources["level_name"].source == "cli"

    def test_list_known_keys_includes_nested_defaults(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"web": {"port": 8080}, "logging": {"level": "normal"}},
        )

        keys = resolver.list_known_keys()

        assert "web.port" in keys
        assert "logging.level" in keys

    def test_resolve_all_includes_nested_default_key(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"web": {"port": 8080}},
        )

        all_config = resolver.resolve_all()

        assert "web.port" in all_config
        assert all_config["web.port"].value == 8080
        assert all_config["web.port"].source == "default"

    def test_unknown_user_key_is_included_and_marked_unknown(self, tmp_path):
        user_config = tmp_path / "config.yaml"
        user_config.write_text(
            """
web:
  port: 8080
magic:
  foo: 123
"""
        )

        resolver = ConfigResolver(
            cli_args={},
            user_config_path=user_config,
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"web": {"port": 8000}},
        )

        all_config = resolver.resolve_all()
        assert "magic.foo" in all_config
        assert all_config["magic.foo"].value == 123
        assert all_config["magic.foo"].source == "user_config"

        schema = resolver.get_key_schema("magic.foo")
        assert schema.unknown is True

    def test_resolve_system_log_defaults(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={},
        )

        assert resolver.resolve_system_log_enabled() is False
        path = resolver.resolve_system_log_path()
        assert isinstance(path, str)
        assert path.strip() != ""
        assert str(Path.home() / ".audiomason" / "system.log") == path

    def test_resolve_system_log_enabled_type_validation(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"logging": {"system_log_enabled": "yes"}},
        )

        with pytest.raises(ConfigError):
            resolver.resolve_system_log_enabled()

    def test_resolve_system_log_path_validation(self, tmp_path):
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=tmp_path / "nonexistent.yaml",
            system_config_path=tmp_path / "nonexistent_system.yaml",
            defaults={"logging": {"system_log_path": "   "}},
        )

        with pytest.raises(ConfigError):
            resolver.resolve_system_log_path()
