#!/usr/bin/env python3
"""Simple test for ConfigResolver without pytest."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audiomason.core.config import ConfigResolver


def test_priority_order():
    """Test that priority order is respected."""
    print("Testing priority order...")

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create config files
        user_config = tmp_path / "user.yaml"
        user_config.write_text("bitrate: 128k\nloudnorm: true\n")

        system_config = tmp_path / "system.yaml"
        system_config.write_text("bitrate: 96k\nloudnorm: false\n")

        # Test 1: CLI overrides everything
        resolver = ConfigResolver(
            cli_args={"bitrate": "320k"},
            user_config_path=user_config,
            system_config_path=system_config,
        )

        bitrate, source = resolver.resolve("bitrate")
        assert bitrate == "320k", f"Expected '320k', got '{bitrate}'"
        assert source == "cli", f"Expected 'cli', got '{source}'"
        print("OK CLI has highest priority")

        # Test 2: User config overrides system
        resolver = ConfigResolver(
            cli_args={},
            user_config_path=user_config,
            system_config_path=system_config,
        )

        bitrate, source = resolver.resolve("bitrate")
        assert bitrate == "128k", f"Expected '128k', got '{bitrate}'"
        assert source == "user_config", f"Expected 'user_config', got '{source}'"
        print("OK User config overrides system config")

        # Test 3: Defaults work
        loudnorm, source = resolver.resolve("split_chapters")  # Not in any config
        assert source == "default", f"Expected 'default', got '{source}'"
        print("OK Defaults work when nothing else provides value")

        # Test 4: Nested keys
        resolver = ConfigResolver(cli_args={"logging": {"level": "debug"}})
        level, source = resolver.resolve("logging.level")
        assert level == "debug", f"Expected 'debug', got '{level}'"
        print("OK Nested keys with dot notation work")

    print("\nOK All tests passed!")


if __name__ == "__main__":
    try:
        test_priority_order()
    except AssertionError as e:
        print(f"\nX Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nX Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
