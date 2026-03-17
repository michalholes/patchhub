# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.fs_jail import FsJail, FsJailError


class TestFsJail(unittest.TestCase):
    def test_resolve_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir()
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=[""],
                allow_crud=True,
            )
            p = jail.resolve_rel("logs")
            self.assertTrue(str(p).startswith(str(root / "patches")))

    def test_reject_escape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir()
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=[""],
                allow_crud=True,
            )
            with self.assertRaises(FsJailError):
                jail.resolve_rel("../x")

    def test_crud_allowlist_root_level_entry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir()
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=[""],
                allow_crud=True,
            )
            jail.assert_crud_allowed("a.zip")

    def test_crud_allowlist_root_level_entry_denied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir()
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=["incoming"],
                allow_crud=True,
            )
            with self.assertRaises(FsJailError):
                jail.assert_crud_allowed("a.zip")

    def test_crud_allowlist_workspace_tree_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir()
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=["workspaces"],
                allow_crud=True,
            )
            jail.assert_crud_allowed("workspaces/issue_501/repo")

    def test_crud_allowlist_subpath_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir()
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=["incoming"],
                allow_crud=True,
            )
            jail.assert_crud_allowed("incoming/a.zip")
