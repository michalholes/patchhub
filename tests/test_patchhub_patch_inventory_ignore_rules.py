# ruff: noqa: E402
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.patch_inventory import build_patch_inventory


class _DummyJail:
    def __init__(self, root: Path, patches_root: str) -> None:
        self._root = root
        self._patches_root = patches_root

    def resolve_rel(self, rel: str) -> Path:
        base = self._root / self._patches_root
        if not rel:
            return base
        return base / rel


class _DummyCore:
    def __init__(self, root: Path) -> None:
        self.cfg = SimpleNamespace(
            paths=SimpleNamespace(
                patches_root="patches",
                upload_dir="patches/incoming",
            ),
            autofill=SimpleNamespace(
                derive_enabled=False,
                scan_ignore_filenames=["ignore.patch"],
                scan_ignore_prefixes=["patched_"],
                zip_commit_enabled=False,
                zip_commit_filename="COMMIT_MESSAGE.txt",
                zip_commit_max_bytes=4096,
                zip_commit_max_ratio=200,
                zip_issue_enabled=False,
                zip_issue_filename="ISSUE_NUMBER.txt",
                zip_issue_max_bytes=128,
                zip_issue_max_ratio=200,
            ),
        )
        self.jail = _DummyJail(root, "patches")


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)


def test_inventory_applies_ignore_rules_to_patches_root_and_upload_dir(
    tmp_path: Path,
) -> None:
    patches_root = tmp_path / "patches"
    upload_dir = patches_root / "incoming"
    upload_dir.mkdir(parents=True)

    ignored_root = patches_root / "ignore.patch"
    ignored_prefix_root = patches_root / "patched_root.diff"
    keep_patch = patches_root / "keep.patch"
    keep_diff = patches_root / "keep.diff"
    keep_bundle = patches_root / "keep_bundle.zip"
    bundle_without_patch = patches_root / "bundle_without_patch.zip"

    ignored_root.write_text("ignored root\n", encoding="ascii")
    ignored_prefix_root.write_text("ignored prefix\n", encoding="ascii")
    keep_patch.write_text("visible patch\n", encoding="ascii")
    keep_diff.write_text("visible diff\n", encoding="ascii")
    _write_zip(keep_bundle, {"nested/file.patch": b"diff --git x"})
    _write_zip(bundle_without_patch, {"README.txt": b"x"})

    ignored_upload = upload_dir / "ignore.patch"
    ignored_prefix_upload = upload_dir / "patched_upload.patch"
    upload_keep = upload_dir / "upload_keep.diff"
    ignored_upload.write_text("ignored upload\n", encoding="ascii")
    ignored_prefix_upload.write_text("ignored upload prefix\n", encoding="ascii")
    upload_keep.write_text("visible upload diff\n", encoding="ascii")
    nested_dir = upload_dir / "nested"
    nested_dir.mkdir()
    (nested_dir / "deep.patch").write_text("hidden nested\n", encoding="ascii")

    ordered = [
        upload_keep,
        keep_patch,
        keep_diff,
        keep_bundle,
        bundle_without_patch,
        ignored_root,
        ignored_prefix_root,
        ignored_upload,
        ignored_prefix_upload,
    ]
    for offset, path in enumerate(reversed(ordered), start=1):
        os.utime(path, (1_000_000_000 + offset, 1_000_000_000 + offset))

    core = _DummyCore(tmp_path)
    _sig, items = build_patch_inventory(core)

    assert [item["stored_rel_path"] for item in items] == [
        "incoming/upload_keep.diff",
        "keep.patch",
        "keep.diff",
        "keep_bundle.zip",
    ]
    assert {item["filename"] for item in items} == {
        "upload_keep.diff",
        "keep.patch",
        "keep.diff",
        "keep_bundle.zip",
    }
    assert {item["kind"] for item in items} == {"diff", "patch", "zip"}
    assert not any(item["filename"] == "ignore.patch" for item in items)
    assert not any(item["filename"].startswith("patched_") for item in items)
    assert not any(item["stored_rel_path"] == "incoming/nested/deep.patch" for item in items)
    assert any(
        item["stored_rel_path"] == "incoming/upload_keep.diff"
        and item["source_bucket"] == "upload_dir"
        for item in items
    )
    assert any(
        item["stored_rel_path"] == "keep.patch" and item["source_bucket"] == "patches_root"
        for item in items
    )
