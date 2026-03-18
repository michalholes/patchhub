"""Integration tests for checkpoint system."""

from audiomason.checkpoint import CheckpointManager
from audiomason.core import ProcessingContext


class TestCheckpointManager:
    """Tests for CheckpointManager."""

    def test_save_and_load_checkpoint(self, sample_context, tmp_path):
        """Test saving and loading checkpoint."""
        manager = CheckpointManager(checkpoint_dir=tmp_path)

        # Save checkpoint
        checkpoint_file = manager.save_checkpoint(sample_context)
        assert checkpoint_file.exists()

        # Load checkpoint
        loaded = manager.load_checkpoint(sample_context.id)

        assert loaded.id == sample_context.id
        assert loaded.source == sample_context.source
        assert loaded.author == sample_context.author
        assert loaded.title == sample_context.title
        assert loaded.state == sample_context.state

    def test_checkpoint_preserves_all_fields(self, sample_context, tmp_path):
        """Test that all context fields are preserved."""
        manager = CheckpointManager(checkpoint_dir=tmp_path)

        # Setup context with various fields
        sample_context.year = 2024
        sample_context.loudnorm = True
        sample_context.split_chapters = True
        sample_context.add_warning("Test warning")
        sample_context.add_timing("step1", 1.5)
        sample_context.mark_step_complete("import")

        # Save and load
        manager.save_checkpoint(sample_context)
        loaded = manager.load_checkpoint(sample_context.id)

        assert loaded.year == 2024
        assert loaded.loudnorm is True
        assert loaded.split_chapters is True
        assert "Test warning" in loaded.warnings
        assert loaded.timings["step1"] == 1.5
        assert "import" in loaded.completed_steps

    def test_list_checkpoints(self, sample_context, tmp_path):
        """Test listing available checkpoints."""
        manager = CheckpointManager(checkpoint_dir=tmp_path)

        # Create multiple checkpoints
        ctx1 = sample_context
        ctx2 = ProcessingContext(
            id="ctx2",
            source=sample_context.source,
            author="Author 2",
            title="Title 2",
        )

        manager.save_checkpoint(ctx1)
        manager.save_checkpoint(ctx2)

        # List checkpoints
        checkpoints = manager.list_checkpoints()

        assert len(checkpoints) == 2
        assert any(cp["id"] == ctx1.id for cp in checkpoints)
        assert any(cp["id"] == ctx2.id for cp in checkpoints)

    def test_delete_checkpoint(self, sample_context, tmp_path):
        """Test deleting checkpoint."""
        manager = CheckpointManager(checkpoint_dir=tmp_path)

        # Save checkpoint
        manager.save_checkpoint(sample_context)

        # Delete
        manager.delete_checkpoint(sample_context.id)

        # Verify deleted
        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 0

    def test_cleanup_old_checkpoints(self, sample_context, tmp_path):
        """Test cleanup of old checkpoints."""
        import time

        manager = CheckpointManager(checkpoint_dir=tmp_path)

        # Save checkpoint
        checkpoint_file = manager.save_checkpoint(sample_context)

        # Make it old (modify mtime)
        old_time = time.time() - (8 * 24 * 60 * 60)  # 8 days ago
        import os

        os.utime(checkpoint_file, (old_time, old_time))

        # Cleanup (threshold: 7 days)
        deleted = manager.cleanup_old_checkpoints(days=7)

        assert deleted == 1
        assert not checkpoint_file.exists()
