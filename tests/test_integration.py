#!/usr/bin/env python3
"""Integration test - demonstrates core + plugin + pipeline working together."""

import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audiomason.core import (
    Pipeline,
    PipelineExecutor,
    PipelineStep,
    PluginLoader,
    ProcessingContext,
    State,
)


def test_integration():
    """Test that core + plugin + pipeline work together."""
    print("[TEST] Integration Test: Core + Plugin + Pipeline\n")

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # ===========================================
        #  1. Setup: Create fake input file
        # ===========================================

        input_file = tmp_path / "test_book.m4a"
        input_file.write_text("fake audio data")

        print(f"\U0001f4c1 Created test file: {input_file}")

        # ===========================================
        #  2. Plugin Loader: Load example plugin
        # ===========================================

        plugins_dir = Path(__file__).parent.parent / "plugins"
        loader = PluginLoader()

        example_plugin_dir = plugins_dir / "example_plugin"
        print(f"\n\U0001f50c Loading plugin from: {example_plugin_dir}")

        loader.load_plugin(example_plugin_dir, validate=False)
        print(f"OK Plugin loaded: {loader.list_plugins()}")

        # ===========================================
        #  3. Context: Create processing context
        # ===========================================

        context = ProcessingContext(
            id=str(uuid.uuid4()),
            source=input_file,
            author="Test Author",
            title="Test Book",
            state=State.PROCESSING,
        )

        print("\n\U0001f4e6 Created context:")
        print(f"   ID: {context.id[:8]}...")
        print(f"   Source: {context.source.name}")
        print(f"   Author: {context.author}")
        print(f"   Title: {context.title}")

        # ===========================================
        #  4. Pipeline: Define simple pipeline
        # ===========================================

        pipeline = Pipeline(
            name="test_pipeline",
            description="Simple test pipeline",
            steps=[
                PipelineStep(
                    id="example_step",
                    plugin="example_plugin",
                    interface="IProcessor",
                    after=[],
                    parallel=False,
                )
            ],
        )

        print("\n\U0001f504 Created pipeline:")
        print(f"   Name: {pipeline.name}")
        print(f"   Steps: {len(pipeline.steps)}")
        print(f"   Step 1: {pipeline.steps[0].id} (plugin: {pipeline.steps[0].plugin})")

        # ===========================================
        #  5. Execute: Run pipeline
        # ===========================================

        print("\n\u26a1 Executing pipeline...")

        executor = PipelineExecutor(loader)

        # Run async function
        import asyncio

        result_context = asyncio.run(executor.execute(pipeline, context))

        # ===========================================
        #  6. Verify: Check results
        # ===========================================

        print("\nOK Pipeline completed!")
        print("\n\U0001f4ca Results:")
        print(f"   State: {result_context.state.value}")
        print(f"   Completed steps: {result_context.completed_steps}")
        print(f"   Warnings: {result_context.warnings}")
        print(f"   Timings: {result_context.timings}")

        # Assertions
        assert "example_step" in result_context.completed_steps
        assert len(result_context.warnings) > 0
        assert "ExamplePlugin" in result_context.warnings[0]
        assert "example_plugin" in result_context.timings

        print("\n\U0001f389 All assertions passed!")


if __name__ == "__main__":
    try:
        test_integration()
        print("\n" + "=" * 50)
        print("OK INTEGRATION TEST PASSED")
        print("=" * 50)
    except AssertionError as e:
        print(f"\nX Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nX Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
