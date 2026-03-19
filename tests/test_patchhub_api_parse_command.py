# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub import app_api_core as core


def _write_runner_config(repo_root: Path) -> None:
    path = repo_root / "scripts" / "am_patch" / "am_patch.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[paths]\ntarget_repo_roots = ["audiomason2=../audiomason2", "/home/pi/patchhub"]\n',
        encoding="utf-8",
    )


def _targeting_self(repo_root: Path) -> object:
    cfg = SimpleNamespace(
        runner=SimpleNamespace(runner_config_toml="scripts/am_patch/am_patch.toml"),
        targeting=SimpleNamespace(default_target_repo="patchhub"),
    )
    return SimpleNamespace(repo_root=repo_root, cfg=cfg)


class TestApiParseCommand(unittest.TestCase):
    def test_parse_ok(self) -> None:
        raw = 'python3 scripts/am_patch.py 219 "x" patches/y.zip'
        status, body = core.api_parse_command(object(), {"raw": raw})
        self.assertEqual(status, 200)
        obj = json.loads(body.decode("utf-8"))
        self.assertTrue(obj.get("ok"))
        self.assertEqual(obj["parsed"]["issue_id"], "219")
        self.assertEqual(obj["parsed"]["commit_message"], "x")
        self.assertEqual(obj["parsed"]["patch_path"], "patches/y.zip")
        self.assertEqual(obj["parsed"]["gate_argv"], [])
        argv = obj["canonical"]["argv"]
        self.assertIn("scripts/am_patch.py", argv)

    def test_parse_accepts_token_bound_target(self) -> None:
        raw = 'python3 scripts/am_patch.py 219 "x" patches/y.zip --target-repo-name audiomason2'
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_runner_config(repo_root)
            status, body = core.api_parse_command(_targeting_self(repo_root), {"raw": raw})
        self.assertEqual(status, 200)
        obj = json.loads(body.decode("utf-8"))
        self.assertTrue(obj.get("ok"))
        self.assertEqual(obj["parsed"]["target_repo"], "audiomason2")

    def test_parse_bad(self) -> None:
        status, body = core.api_parse_command(object(), {"raw": "python3 x.py 1 a b"})
        self.assertEqual(status, 400)
        obj = json.loads(body.decode("utf-8"))
        self.assertFalse(obj.get("ok"))

    def test_parse_rejects_runtime_invalid_target(self) -> None:
        raw = 'python3 scripts/am_patch.py 219 "x" patches/y.zip --target-repo-name bogus'
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_runner_config(repo_root)
            status, body = core.api_parse_command(_targeting_self(repo_root), {"raw": raw})
        self.assertEqual(status, 400)
        obj = json.loads(body.decode("utf-8"))
        self.assertFalse(obj.get("ok"))
        self.assertIn("target_repo", obj["error"])
