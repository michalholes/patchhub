"""Issue 219: renderer must not drift by branching on step_id.

Renderer should be driven by the catalog step schema.
"""

from __future__ import annotations

from pathlib import Path


def test_cli_renderer_has_no_step_id_specific_branches() -> None:
    p = Path("plugins/import/cli_renderer.py")
    txt = p.read_text(encoding="utf-8")

    # Known step_ids must not appear in renderer implementation.
    for step_id in [
        "select_authors",
        "select_books",
        "conflicts_review",
        "final_summary_confirm",
        "plan_preview_batch",
        "processing",
    ]:
        assert step_id not in txt
