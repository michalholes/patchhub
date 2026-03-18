from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _zip_subset_head_markup(html: str) -> str:
    match = re.search(
        r'<div class="zip-subset-list-head">(?P<head>.*?)</div>\s*'
        r'<div id="zipSubsetModalList"',
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group("head")


def test_main_ui_contains_zip_subset_and_progress_applied_hooks() -> None:
    html = (REPO_ROOT / "scripts" / "patchhub" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="zipSubsetStrip"' in html
    assert 'id="zipSubsetModal"' in html
    assert 'id="progressApplied"' in html
    assert 'id="zipSubsetModalTitle"' in html
    assert 'id="zipSubsetModalSubtitle"' in html
    assert 'id="zipSubsetSelectionCount"' in html
    assert 'id="zipSubsetApplyBtn"' in html
    head = _zip_subset_head_markup(html)
    assert ">patch<" not in head
    assert ">Repo path<" in head


def test_app_boot_sequence_loads_zip_subset_modules() -> None:
    app_js = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js").read_text(encoding="utf-8")
    assert "/static/app_part_zip_subset_modal.js" in app_js
    assert "/static/app_part_zip_subset.js" in app_js


def test_zip_subset_modal_is_hidden_by_css_specificity_rule() -> None:
    css = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".modal-backdrop.hidden" in css
    assert "display: none;" in css


def test_zip_subset_modal_uses_patchhub_blue_surface() -> None:
    css = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app.css").read_text(encoding="utf-8")
    assert "background: #121f3b;" in css
    assert "background: #0f1c33;" in css
    assert "background: #141414;" not in css


def test_zip_subset_runtime_exports_match_queue_upload_calls() -> None:
    subset_js = (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    ).read_text(encoding="utf-8")
    queue_js = (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_queue_upload.js"
    ).read_text(encoding="utf-8")
    for capability in [
        "syncZipSubsetUiFromInputs",
        "applyZipSubsetPreview",
        "getZipSubsetValidationState",
        "getZipSubsetEnqueuePayload",
    ]:
        assert capability in queue_js
        assert capability in subset_js


def test_zip_subset_modal_contract_matches_approved_layout_copy() -> None:
    subset_js = (
        REPO_ROOT / "scripts" / "patchhub" / "static" / "app_part_zip_subset.js"
    ).read_text(encoding="utf-8")
    html = (REPO_ROOT / "scripts" / "patchhub" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "Select target files (" in subset_js
    assert "Contents of " in subset_js
    assert "All " in subset_js
    assert " selected" in subset_js
    assert 'id="zipSubsetApplyBtn"' in html
    assert "Cancel" in html
    assert "Apply" in html
