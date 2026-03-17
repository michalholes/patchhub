# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_fs import api_fs_stat
from patchhub.fs_jail import FsJail


class _Dummy:
    def __init__(self, jail: FsJail) -> None:
        self.jail = jail


class TestApiFsStat(unittest.TestCase):
    def test_empty_path_exists_true(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir()
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=[""],
                allow_crud=True,
            )
            dummy = _Dummy(jail)
            status, data = api_fs_stat(dummy, "")
            self.assertEqual(status, 200)
            obj = json.loads(data.decode("utf-8"))
            self.assertTrue(obj.get("ok"))
            self.assertEqual(obj.get("path"), "")
            self.assertEqual(obj.get("exists"), True)

    def test_non_existing_file_exists_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir()
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=[""],
                allow_crud=True,
            )
            dummy = _Dummy(jail)
            status, data = api_fs_stat(dummy, "nope.zip")
            self.assertEqual(status, 200)
            obj = json.loads(data.decode("utf-8"))
            self.assertTrue(obj.get("ok"))
            self.assertEqual(obj.get("path"), "nope.zip")
            self.assertEqual(obj.get("exists"), False)

    def test_existing_file_exists_true(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pdir = root / "patches"
            pdir.mkdir()
            (pdir / "a.zip").write_bytes(b"x")
            jail = FsJail(
                repo_root=root,
                patches_root_rel="patches",
                crud_allowlist=[""],
                allow_crud=True,
            )
            dummy = _Dummy(jail)
            status, data = api_fs_stat(dummy, "a.zip")
            self.assertEqual(status, 200)
            obj = json.loads(data.decode("utf-8"))
            self.assertTrue(obj.get("ok"))
            self.assertEqual(obj.get("path"), "a.zip")
            self.assertEqual(obj.get("exists"), True)
