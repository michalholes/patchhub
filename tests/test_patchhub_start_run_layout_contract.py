from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_start_run_layout_contract_matches_compact_layout() -> None:
    html = (REPO_ROOT / "scripts" / "patchhub" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    css = (REPO_ROOT / "scripts" / "patchhub" / "static" / "app.css").read_text(encoding="utf-8")
    assert "B) Start run" not in html
    assert '<label class="lbl">Mode</label>' not in html
    assert 'id="mode" class="input start-run-mode"' in html
    assert 'id="patchPath"' in html
    assert 'class="input start-run-patch"' in html
    assert 'id="gateOptionsBtn"' in html
    assert 'id="browsePatch" class="btn btn-small hidden"' in html
    assert 'id="issueId"' in html
    assert 'class="input start-run-issue"' in html
    assert 'id="liveAutoscrollToggle"' in html
    assert 'id="uiStatusBar"' in html
    assert 'role="button"' in html
    assert 'id="uiStatusModal"' in html
    assert 'id="uploadHint" class="muted hidden"' in html
    assert 'id="enqueueHint" class="muted hidden"' in html
    assert 'id="fsHint" class="muted hidden"' in html
    assert 'id="parseHint" class="muted hidden"' in html
    assert "Auto-scroll" in html
    top_row = html.split('<select id="mode" class="input start-run-mode">', 1)[1]
    top_row = top_row.split("</div>", 1)[0]
    assert '<span class="spacer"></span>' not in top_row
    assert top_row.index('id="patchPath"') < top_row.index('id="gateOptionsBtn"')
    assert ".start-run-mode" in css
    assert "flex: 0 0 150px;" in css
    assert "width: 150px;" in css
    assert ".start-run-issue" in css
    assert "flex: 0 0 50px;" in css
    assert "width: 50px;" in css
    assert ".start-run-patch" in css
    assert "flex: 1 1 0;" in css
    assert "width: auto;" in css
