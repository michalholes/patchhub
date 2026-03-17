"""Unit tests for core.context module."""

from audiomason.core.context import (
    CoverChoice,
    PreflightResult,
    ProcessingContext,
    State,
)


class TestProcessingContext:
    """Tests for ProcessingContext."""

    def test_create_context(self, temp_audio_file):
        """Test creating a context."""
        ctx = ProcessingContext(
            id="test123",
            source=temp_audio_file,
        )

        assert ctx.id == "test123"
        assert ctx.source == temp_audio_file
        assert ctx.state == State.INIT
        assert ctx.progress == 0.0

    def test_add_timing(self, sample_context):
        """Test adding timing."""
        sample_context.add_timing("step1", 1.5)
        sample_context.add_timing("step2", 2.5)

        assert "step1" in sample_context.timings
        assert sample_context.timings["step1"] == 1.5
        assert sample_context.timings["step2"] == 2.5

    def test_add_error(self, sample_context):
        """Test adding error."""
        error = Exception("Test error")
        sample_context.add_error(error)

        assert len(sample_context.errors) == 1
        assert sample_context.errors[0] == error
        assert sample_context.has_errors

    def test_add_warning(self, sample_context):
        """Test adding warning."""
        sample_context.add_warning("Warning 1")
        sample_context.add_warning("Warning 2")

        assert len(sample_context.warnings) == 2
        assert "Warning 1" in sample_context.warnings

    def test_mark_step_complete(self, sample_context):
        """Test marking step complete."""
        sample_context.mark_step_complete("import")
        sample_context.mark_step_complete("convert")

        assert "import" in sample_context.completed_steps
        assert "convert" in sample_context.completed_steps
        assert len(sample_context.completed_steps) == 2

    def test_total_time(self, sample_context):
        """Test total time calculation."""
        sample_context.start_time = 1000.0
        sample_context.end_time = 1050.5

        assert sample_context.total_time == 50.5


class TestState:
    """Tests for State enum."""

    def test_state_values(self):
        """Test state enum values."""
        assert State.INIT.value == "init"
        assert State.PROCESSING.value == "processing"
        assert State.DONE.value == "done"
        assert State.ERROR.value == "error"


class TestCoverChoice:
    """Tests for CoverChoice enum."""

    def test_cover_choice_values(self):
        """Test cover choice enum values."""
        assert CoverChoice.EMBEDDED.value == "embedded"
        assert CoverChoice.FILE.value == "file"
        assert CoverChoice.URL.value == "url"
        assert CoverChoice.SKIP.value == "skip"


class TestPreflightResult:
    """Tests for PreflightResult."""

    def test_create_preflight_result(self):
        """Test creating preflight result."""
        result = PreflightResult()

        assert result.has_title is False
        assert result.has_author is False
        assert result.has_embedded_cover is False
        assert result.chapter_count == 0

    def test_preflight_with_data(self):
        """Test preflight with detected data."""
        result = PreflightResult(
            has_title=True,
            has_author=True,
            guessed_author="Test Author",
            guessed_title="Test Title",
            has_chapters=True,
            chapter_count=15,
        )

        assert result.has_title
        assert result.has_author
        assert result.guessed_author == "Test Author"
        assert result.chapter_count == 15
