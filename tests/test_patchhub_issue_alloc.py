# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.issue_alloc import allocate_next_issue_id


class TestIssueAlloc(unittest.TestCase):
    def test_allocate_start(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "logs").mkdir(parents=True)
            n = allocate_next_issue_id(root, r"issue_(\d+)", 1, 99999)
            self.assertEqual(n, 1)

    def test_allocate_next(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "logs").mkdir(parents=True)
            (root / "logs" / "am_patch_issue_41_x.log").write_text("hi", encoding="utf-8")
            n = allocate_next_issue_id(root, r"issue_(\d+)", 1, 99999)
            self.assertEqual(n, 42)
