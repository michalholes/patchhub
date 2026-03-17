from __future__ import annotations

import sys
from pathlib import Path


def _import_gate():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.gates import check_docs_gate

    return check_docs_gate


def test_docs_gate_not_triggered_when_no_watched_changes() -> None:
    check_docs_gate = _import_gate()
    ok, missing, trigger = check_docs_gate(
        ["patches/x.txt", "badguys/y.txt"],
        include=["src", "plugins"],
        exclude=["badguys", "patches"],
        required_files=["docs/change_fragments/"],
        changed_entries=[("M ", "patches/x.txt")],
    )
    assert ok is True
    assert missing == []
    assert trigger is None


def test_docs_gate_fails_when_triggered_and_fragment_missing() -> None:
    check_docs_gate = _import_gate()
    ok, missing, trigger = check_docs_gate(
        ["src/a.py"],
        include=["src", "plugins"],
        exclude=["badguys", "patches"],
        required_files=["docs/change_fragments/"],
        changed_entries=[("M ", "src/a.py")],
    )
    assert ok is False
    assert trigger == "src/a.py"
    assert missing == ["docs/change_fragments/"]


def test_docs_gate_fails_when_only_modified_fragment_exists() -> None:
    check_docs_gate = _import_gate()
    ok, missing, trigger = check_docs_gate(
        ["plugins/p.py", "docs/change_fragments/existing.md"],
        include=["src", "plugins"],
        exclude=["badguys", "patches"],
        required_files=["docs/change_fragments/"],
        changed_entries=[
            ("M ", "plugins/p.py"),
            ("M ", "docs/change_fragments/existing.md"),
        ],
    )
    assert ok is False
    assert trigger == "plugins/p.py"
    assert missing == ["docs/change_fragments/"]


def test_docs_gate_passes_when_added_fragment_exists() -> None:
    check_docs_gate = _import_gate()
    ok, missing, trigger = check_docs_gate(
        ["plugins/p.py", "docs/change_fragments/new_fragment.md"],
        include=["src", "plugins"],
        exclude=["badguys", "patches"],
        required_files=["docs/change_fragments/"],
        changed_entries=[
            ("M ", "plugins/p.py"),
            ("A ", "docs/change_fragments/new_fragment.md"),
        ],
    )
    assert ok is True
    assert missing == []
    assert trigger == "plugins/p.py"


def test_docs_gate_respects_required_files_override() -> None:
    check_docs_gate = _import_gate()
    ok, missing, trigger = check_docs_gate(
        ["src/a.py", "docs/change_fragments/override.md"],
        include=["src"],
        exclude=["badguys", "patches"],
        required_files=["docs/change_fragments/"],
        changed_entries=[
            ("M ", "src/a.py"),
            ("??", "docs/change_fragments/override.md"),
        ],
    )
    assert ok is True
    assert missing == []
    assert trigger == "src/a.py"
