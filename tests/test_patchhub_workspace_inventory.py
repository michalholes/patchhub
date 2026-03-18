# ruff: noqa: E402
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.workspace_inventory import list_workspaces


class _DummyCore:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.patches_root = repo_root / "patches"
        self.jobs_root = repo_root / "patches" / "artifacts" / "web_jobs"
        self.web_jobs_db = None
        self.cfg = SimpleNamespace(
            paths=SimpleNamespace(patches_root="patches"),
            runner=SimpleNamespace(runner_config_toml="scripts/am_patch/am_patch.toml"),
            indexing=SimpleNamespace(log_filename_regex=r"am_patch_issue_(\d+)_"),
        )


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class TestPatchhubWorkspaceInventory(unittest.TestCase):
    def test_dirty_workspace_reports_busy_and_union_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            patches = root / "patches"
            ws_repo = patches / "workspaces" / "issue_501" / "repo"
            ws_repo.mkdir(parents=True)
            (root / "scripts" / "am_patch").mkdir(parents=True)
            (root / "scripts" / "am_patch" / "am_patch.toml").write_text("", encoding="utf-8")
            _git(["init"], ws_repo)
            _git(["config", "user.email", "test@example.com"], ws_repo)
            _git(["config", "user.name", "Tester"], ws_repo)
            (ws_repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            _git(["add", "tracked.txt"], ws_repo)
            _git(["commit", "-m", "base"], ws_repo)
            (ws_repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
            ws_root = ws_repo.parent
            (ws_root / "meta.json").write_text(
                json.dumps({"attempt": 3, "message": "Implement workspace inventory"}),
                encoding="utf-8",
            )
            (ws_root / ".am_patch_state.json").write_text(
                json.dumps({"base_sha": "abc", "allowed_union": ["a", "b"]}),
                encoding="utf-8",
            )
            core = _DummyCore(root)
            busy_job = SimpleNamespace(status="queued", issue_id="501")
            sig, items = list_workspaces(core, [busy_job])
            self.assertTrue(sig.startswith("workspaces:"))
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item["issue_id"], 501)
            self.assertEqual(item["workspace_rel_path"], "workspaces/issue_501")
            self.assertEqual(item["state"], "DIRTY")
            self.assertEqual(item["busy"], True)
            self.assertEqual(item["attempt"], 3)
            self.assertEqual(item["allowed_union_count"], 2)
            self.assertEqual(item["commit_summary"], "Implement workspace inventory")

    def test_clean_workspace_after_success_is_kept_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            patches = root / "patches"
            logs = patches / "logs"
            logs.mkdir(parents=True)
            ws_repo = patches / "workspaces" / "issue_502" / "repo"
            ws_repo.mkdir(parents=True)
            (root / "scripts" / "am_patch").mkdir(parents=True)
            (root / "scripts" / "am_patch" / "am_patch.toml").write_text("", encoding="utf-8")
            _git(["init"], ws_repo)
            _git(["config", "user.email", "test@example.com"], ws_repo)
            _git(["config", "user.name", "Tester"], ws_repo)
            (ws_repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            _git(["add", "tracked.txt"], ws_repo)
            _git(["commit", "-m", "base"], ws_repo)
            (ws_repo.parent / "meta.json").write_text(
                json.dumps({"attempt": 1, "message": "Keep clean workspace"}),
                encoding="utf-8",
            )
            (logs / "am_patch_issue_502_demo.log").write_text(
                "hello\nRESULT: SUCCESS\n",
                encoding="utf-8",
            )
            core = _DummyCore(root)
            _sig, items = list_workspaces(core, [])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["state"], "KEPT_AFTER_SUCCESS")
            self.assertEqual(items[0]["busy"], False)

    def test_clean_workspace_after_newer_canceled_run_is_not_kept_after_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            patches = root / "patches"
            ws_repo = patches / "workspaces" / "issue_503" / "repo"
            ws_repo.mkdir(parents=True)
            (root / "scripts" / "am_patch").mkdir(parents=True)
            (root / "scripts" / "am_patch" / "am_patch.toml").write_text("", encoding="utf-8")
            _git(["init"], ws_repo)
            _git(["config", "user.email", "test@example.com"], ws_repo)
            _git(["config", "user.name", "Tester"], ws_repo)
            (ws_repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            _git(["add", "tracked.txt"], ws_repo)
            _git(["commit", "-m", "base"], ws_repo)
            (ws_repo.parent / "meta.json").write_text(
                json.dumps({"attempt": 1, "message": "Canceled run wins"}),
                encoding="utf-8",
            )
            core = _DummyCore(root)
            with (
                patch(
                    "patchhub.indexing.iter_runs",
                    return_value=[
                        SimpleNamespace(
                            issue_id=503,
                            result="success",
                            mtime_utc="2026-01-01T00:00:00Z",
                            log_rel_path="logs/am_patch_issue_503_success.log",
                        )
                    ],
                ),
                patch(
                    "patchhub.workspace_inventory._iter_canceled_runs",
                    return_value=[
                        SimpleNamespace(
                            issue_id=503,
                            result="canceled",
                            mtime_utc="2026-01-02T00:00:00Z",
                            log_rel_path="artifacts/web_jobs/job_1/am_patch_issue_503.jsonl",
                        )
                    ],
                ),
            ):
                _sig, items = list_workspaces(core, [])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["state"], "CLEAN")
            self.assertEqual(items[0]["busy"], False)
