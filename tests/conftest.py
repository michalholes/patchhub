"""Pytest configuration and fixtures."""

import sys
from pathlib import Path

import pytest

# Add repo root and src to path (for 'plugins.*' and 'audiomason.*' imports)
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "src"))


@pytest.fixture(autouse=True)
def _isolate_generic_plugin_module():
    """Ensure 'plugin' module cache does not leak between tests.

    Some tests temporarily add a plugin directory to sys.path and import from a local
    plugin.py via `import plugin` / `from plugin import ...`. If another test (or the
    plugin loader) has already populated sys.modules['plugin'], Python will reuse that
    cached module even when sys.path changes.
    """
    sys.modules.pop("plugin", None)
    yield
    sys.modules.pop("plugin", None)


@pytest.fixture
def temp_audio_file(tmp_path):
    """Create temporary fake audio file.

    Args:
        tmp_path: pytest temporary directory

    Returns:
        Path to fake M4A file
    """
    audio_file = tmp_path / "test_book.m4a"
    audio_file.write_text("fake audio data")
    return audio_file


@pytest.fixture
def sample_context(temp_audio_file):
    """Create sample ProcessingContext.

    Args:
        temp_audio_file: Fake audio file

    Returns:
        ProcessingContext instance
    """
    import uuid

    from audiomason.core import ProcessingContext, State

    return ProcessingContext(
        id=str(uuid.uuid4()),
        source=temp_audio_file,
        author="Test Author",
        title="Test Book",
        year=2024,
        state=State.INIT,
    )


@pytest.fixture
def plugin_loader(tmp_path):
    """Create PluginLoader with test plugins dir.

    Args:
        tmp_path: pytest temporary directory

    Returns:
        PluginLoader instance
    """
    from audiomason.core import PluginLoader

    plugins_dir = Path(__file__).parent.parent / "plugins"
    return PluginLoader(builtin_plugins_dir=plugins_dir)


@pytest.fixture
def pipeline_executor(plugin_loader):
    """Create PipelineExecutor.

    Args:
        plugin_loader: PluginLoader fixture

    Returns:
        PipelineExecutor instance
    """
    from audiomason.core import PipelineExecutor

    return PipelineExecutor(plugin_loader)


@pytest.fixture
def config_resolver():
    """Create ConfigResolver with defaults.

    Returns:
        ConfigResolver instance
    """
    from audiomason.core import ConfigResolver

    return ConfigResolver(cli_args={}, defaults={})
