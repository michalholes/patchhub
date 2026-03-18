# ruff: noqa: E402
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_workspaces import api_workspaces


class _DummyCore:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.patches_root = repo_root / "patches"
        self.cfg = SimpleNamespace(
            paths=SimpleNamespace(patches_root="patches"),
            runner=SimpleNamespace(runner_config_toml="scripts/am_patch/am_patch.toml"),
            indexing=SimpleNamespace(log_filename_regex=r"am_patch_issue_(\d+)_"),
        )


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class TestPatchhubApiWorkspaces(unittest.TestCase):
    def test_api_workspaces_returns_ok_items_and_sig(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws_repo = root / "patches" / "workspaces" / "issue_777" / "repo"
            ws_repo.mkdir(parents=True)
            (root / "scripts" / "am_patch").mkdir(parents=True)
            (root / "scripts" / "am_patch" / "am_patch.toml").write_text("", encoding="utf-8")
            _git(["init"], ws_repo)
            _git(["config", "user.email", "test@example.com"], ws_repo)
            _git(["config", "user.name", "Tester"], ws_repo)
            (ws_repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            _git(["add", "tracked.txt"], ws_repo)
            _git(["commit", "-m", "base"], ws_repo)
            status, data = api_workspaces(_DummyCore(root), [])
            self.assertEqual(status, 200)
            obj = json.loads(data.decode("utf-8"))
            self.assertTrue(obj.get("ok"))
            self.assertTrue(str(obj.get("sig", "")).startswith("workspaces:"))
            self.assertEqual(obj["items"][0]["issue_id"], 777)
