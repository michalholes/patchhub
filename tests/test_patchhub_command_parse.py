# ruff: noqa: E402
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.command_parse import CommandParseError, parse_runner_command


class TestCommandParse(unittest.TestCase):
    def test_parse_patch(self) -> None:
        c = 'python3 scripts/am_patch.py 1000 "Issue #1000: test" patches/x.zip'
        p = parse_runner_command(c)
        self.assertEqual(p.mode, "patch")
        self.assertEqual(p.issue_id, "1000")
        self.assertEqual(p.patch_path, "patches/x.zip")
        self.assertEqual(p.gate_argv, [])

    def test_parse_finalize(self) -> None:
        c = 'python3 scripts/am_patch.py -f "Issue #1000: finalize"'
        p = parse_runner_command(c)
        self.assertEqual(p.mode, "finalize_live")
        self.assertEqual(p.commit_message, "Issue #1000: finalize")

    def test_parse_rerun_latest_with_gate_overrides(self) -> None:
        c = (
            'python3 scripts/am_patch.py 534 "Rerun issue 534" '
            "patches/issue_534_v1.zip -l --skip-pytest --override compile_check=true"
        )
        p = parse_runner_command(c)
        self.assertEqual(p.mode, "rerun_latest")
        self.assertEqual(p.issue_id, "534")
        self.assertEqual(p.commit_message, "Rerun issue 534")
        self.assertEqual(p.patch_path, "patches/issue_534_v1.zip")
        self.assertEqual(
            p.gate_argv,
            ["--override", "compile_check=true", "--skip-pytest"],
        )
        self.assertEqual(
            p.canonical_argv,
            [
                "python3",
                "scripts/am_patch.py",
                "534",
                "Rerun issue 534",
                "patches/issue_534_v1.zip",
                "-l",
                "--override",
                "compile_check=true",
                "--skip-pytest",
            ],
        )

    def test_parse_finalize_live_with_gate_overrides(self) -> None:
        p = parse_runner_command(
            'python3 scripts/am_patch.py -f "Issue #1000: finalize" --skip-ruff'
        )
        self.assertEqual(p.mode, "finalize_live")
        self.assertEqual(p.commit_message, "Issue #1000: finalize")
        self.assertEqual(p.gate_argv, ["--skip-ruff"])
        self.assertEqual(
            p.canonical_argv,
            [
                "python3",
                "scripts/am_patch.py",
                "-f",
                "Issue #1000: finalize",
                "--skip-ruff",
            ],
        )

    def test_missing_runner(self) -> None:
        with self.assertRaises(CommandParseError):
            parse_runner_command("python3 x.py 1 a b")
