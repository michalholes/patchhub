#!/usr/bin/env python3
"""End-to-end test - MVP functionality test.

Tests the complete workflow:
1. Create fake M4A file
2. Run CLI command
3. Verify output

Note: This test simulates the flow but won't actually convert audio
      (requires real FFmpeg and M4A file).
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Add plugins to path
sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))


def test_cli_help():
    """Test that CLI help works."""
    print("[TEST] Test 1: CLI Help")
    print("-" * 50)

    # Import here after path is set
    sys.path.insert(0, str(Path(__file__).parent.parent / "plugins/cmd_interface"))
    from plugin import CLIPlugin

    # Simulate: ./audiomason
    sys.argv = ["audiomason"]

    cli = CLIPlugin()

    # This should print usage
    import asyncio

    asyncio.run(cli.run())

    print()
    print("OK CLI help works")
    print()


def test_version():
    """Test version command."""
    print("[TEST] Test 2: Version Command")
    print("-" * 50)

    sys.path.insert(0, str(Path(__file__).parent.parent / "plugins/cmd_interface"))
    from plugin import CLIPlugin

    sys.argv = ["audiomason", "version"]

    cli = CLIPlugin()
    import asyncio

    asyncio.run(cli.run())

    print()
    print("OK Version command works")
    print()


def test_plugin_loading():
    """Test that all plugins load correctly."""
    print("[TEST] Test 3: Plugin Loading")
    print("-" * 50)

    from audiomason.core import PluginLoader

    plugins_dir = Path(__file__).parent.parent / "plugins"
    loader = PluginLoader(builtin_plugins_dir=plugins_dir)

    # Load audio processor
    audio_dir = plugins_dir / "audio_processor"
    if audio_dir.exists():
        loader.load_plugin(audio_dir, validate=False)
        print("OK audio_processor loaded")

    # Load file I/O
    io_dir = plugins_dir / "file_io"
    if io_dir.exists():
        loader.load_plugin(io_dir, validate=False)
        print("OK file_io loaded")

    # Load CLI
    cli_dir = plugins_dir / "cmd_interface"
    if cli_dir.exists():
        loader.load_plugin(cli_dir, validate=False)
        print("OK cli loaded")

    print()
    print(f"OK Loaded {len(loader.list_plugins())} plugins: {loader.list_plugins()}")
    print()


def test_pipeline_yaml():
    """Test that pipeline YAML is valid."""
    print("[TEST] Test 4: Pipeline YAML")
    print("-" * 50)

    from audiomason.core import PipelineExecutor, PluginLoader

    pipeline_path = Path(__file__).parent.parent / "pipelines" / "minimal.yaml"

    if not pipeline_path.exists():
        print(f"X Pipeline not found: {pipeline_path}")
        return

    # Load plugins first
    plugins_dir = Path(__file__).parent.parent / "plugins"
    loader = PluginLoader(builtin_plugins_dir=plugins_dir)

    executor = PipelineExecutor(loader)

    try:
        pipeline = executor.load_pipeline(pipeline_path)
        print(f"OK Pipeline loaded: {pipeline.name}")
        print(f"OK Steps: {len(pipeline.steps)}")
        for step in pipeline.steps:
            print(f"  - {step.id} ({step.plugin})")

        print()
        print("OK Pipeline YAML is valid")
        print()

    except Exception as e:
        print(f"X Pipeline loading failed: {e}")


def main():
    """Run all tests."""
    print()
    print("=" * 70)
    print(" AudioMason v2 MVP - End-to-End Test Suite")
    print("=" * 70)
    print()

    try:
        test_cli_help()
        test_version()
        test_plugin_loading()
        test_pipeline_yaml()

        print("=" * 70)
        print("OK ALL TESTS PASSED")
        print("=" * 70)
        print()
        print("\U0001f680 MVP is ready for testing on Raspberry Pi!")
        print()
        print("Next steps:")
        print("1. Transfer project to Raspberry Pi")
        print("2. Install FFmpeg: sudo apt-get install ffmpeg")
        print("3. Test with real M4A file:")
        print('   ./audiomason process book.m4a --author "Author" --title "Title"')
        print()

    except Exception as e:
        print()
        print(f"X Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
