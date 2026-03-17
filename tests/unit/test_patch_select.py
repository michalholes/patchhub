import sys
from pathlib import Path

import pytest


def _add_scripts_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(scripts_dir))


def test_choose_default_patch_input_selects_unique(tmp_path):
    _add_scripts_to_path()
    from am_patch.patch_select import choose_default_patch_input

    patch_dir = tmp_path / "patches"
    patch_dir.mkdir()

    # When none exists, default is issue_{id}.py (even if missing).
    p = choose_default_patch_input(patch_dir, 42)
    assert p.name == "issue_42.py"

    # Prefer the only existing candidate.
    (patch_dir / "issue_42.patch").write_text("x")
    p2 = choose_default_patch_input(patch_dir, 42)
    assert p2.name == "issue_42.patch"


def test_choose_default_patch_input_ambiguous(tmp_path):
    _add_scripts_to_path()
    from am_patch.patch_select import PatchSelectError, choose_default_patch_input

    patch_dir = tmp_path / "patches"
    patch_dir.mkdir()
    (patch_dir / "issue_7.py").write_text("x")
    (patch_dir / "issue_7.patch").write_text("y")

    with pytest.raises(PatchSelectError):
        choose_default_patch_input(patch_dir, 7)


def test_decide_unified_mode_auto_and_explicit(tmp_path):
    _add_scripts_to_path()
    from am_patch.patch_select import PatchSelectError, decide_unified_mode

    p_py = tmp_path / "x.py"
    p_py.write_text("print('hi')")

    p_patch = tmp_path / "x.patch"
    p_patch.write_text("diff --git a/a b/a\n")

    assert decide_unified_mode(p_py, explicit_unified=False) is False
    assert decide_unified_mode(p_patch, explicit_unified=False) is True
    assert decide_unified_mode(p_patch, explicit_unified=True) is True

    with pytest.raises(PatchSelectError):
        decide_unified_mode(p_py, explicit_unified=True)


def test_decide_unified_mode_zip(tmp_path):
    _add_scripts_to_path()
    from am_patch.patch_select import PatchSelectError, decide_unified_mode

    zip_ok = tmp_path / "ok.zip"
    import zipfile

    with zipfile.ZipFile(zip_ok, "w") as z:
        z.writestr("a.patch", "diff --git a/a b/a\n")

    assert decide_unified_mode(zip_ok, explicit_unified=False) is True
    assert decide_unified_mode(zip_ok, explicit_unified=True) is True

    zip_bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_bad, "w") as z:
        z.writestr("note.txt", "nope")

    with pytest.raises(PatchSelectError):
        decide_unified_mode(zip_bad, explicit_unified=False)
    with pytest.raises(PatchSelectError):
        decide_unified_mode(zip_bad, explicit_unified=True)
