# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_core import api_runs


class _DummyCore:
    def __init__(self) -> None:
        self.repo_root = Path(".")
        self.patches_root = Path("patches")
        self.jobs_root = Path("patches") / "artifacts" / "web_jobs"
        self.web_jobs_db = None
        self.cfg = SimpleNamespace(
            indexing=SimpleNamespace(log_filename_regex=r"am_patch_issue_(\d+)_"),
            paths=SimpleNamespace(patches_root="patches"),
            runner=SimpleNamespace(runner_config_toml="scripts/am_patch/am_patch.toml"),
        )

    def issue_title_for(self, _issue_id: int) -> str:
        return "Issue"


class TestPatchhubApiRunsFallback(unittest.TestCase):
    def test_api_runs_uses_jobs_root_for_canceled_runs_signature_and_items(
        self,
    ) -> None:
        core = _DummyCore()
        decorated = {
            "issue_id": 525,
            "result": "canceled",
            "mtime_utc": "2026-03-11T20:00:00Z",
            "log_rel_path": "artifacts/web_jobs/job_1/am_patch_issue_525.jsonl",
        }
        with (
            patch("patchhub.app_api_core.runs_signature", return_value=(1, 2, 3)),
            patch(
                "patchhub.app_api_core.canceled_runs_signature",
                return_value=(4, 5),
            ) as canceled_sig,
            patch("patchhub.app_api_core.iter_runs", return_value=[]),
            patch(
                "patchhub.app_api_core._iter_canceled_runs",
                return_value=[SimpleNamespace(**decorated)],
            ) as canceled_iter,
            patch("patchhub.app_api_core.compute_success_archive_rel", return_value=None),
            patch("patchhub.app_api_core._decorate_run", side_effect=lambda run, **_: run),
            patch(
                "patchhub.app_api_core.run_to_list_item_json",
                side_effect=lambda run: dict(run.__dict__),
            ),
        ):
            status, payload = api_runs(core, {"limit": "80"})
        self.assertEqual(status, 200)
        canceled_sig.assert_called_once_with(core.jobs_root)
        canceled_iter.assert_called_once_with(core.jobs_root)
        body = json.loads(payload.decode("utf-8"))
        self.assertEqual(body["sig"], "runs:r=1:2:3:c=4:5")
        self.assertEqual(body["runs"][0]["result"], "canceled")
