# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import unittest

from patchhub.indexing import parse_run_result_from_log_text


class TestIndexParseResult(unittest.TestCase):
    def test_success(self) -> None:
        res, line = parse_run_result_from_log_text("x\nRESULT: SUCCESS\n")
        self.assertEqual(res, "success")
        self.assertEqual(line, "RESULT: SUCCESS")

    def test_fail_with_error_detail_records(self) -> None:
        text = (
            "ERROR DETAIL: PREFLIGHT:PATCH_ASCII: bad patch\n"
            "AM_PATCH_FAILURE_FINGERPRINT:\n"
            "- stage: PREFLIGHT\n"
            "RESULT: FAIL\n"
        )
        res, line = parse_run_result_from_log_text(text)
        self.assertEqual(res, "fail")
        self.assertEqual(line, "RESULT: FAIL")

    def test_unknown(self) -> None:
        res, line = parse_run_result_from_log_text("nope\n")
        self.assertEqual(res, "unknown")
        self.assertIsNone(line)
