# ruff: noqa: E402
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.async_queue import _inject_web_overrides


class TestPatchhubAsyncQueueOverrides(unittest.TestCase):
    def test_injects_handshake_overrides_after_am_patch_script(self) -> None:
        argv = ["python3", "scripts/am_patch.py", "500", "msg", "patches/x.zip"]
        with patch(
            "patchhub.asgi.async_queue.job_socket_path",
            return_value="/tmp/audiomason/patchhub_job-500.sock",
        ):
            out = _inject_web_overrides(
                argv,
                "job-500",
                ipc_handshake_wait_s=1,
            )

        self.assertEqual(
            out,
            [
                "python3",
                "scripts/am_patch.py",
                "--override",
                "patch_layout_json_dir=artifacts/web_jobs/job-500",
                "--override",
                "ipc_socket_enabled=true",
                "--override",
                "ipc_handshake_enabled=true",
                "--override",
                "ipc_handshake_wait_s=1",
                "--override",
                "ipc_socket_path=/tmp/audiomason/patchhub_job-500.sock",
                "500",
                "msg",
                "patches/x.zip",
            ],
        )

    def test_does_not_duplicate_existing_handshake_overrides(self) -> None:
        argv = [
            "python3",
            "scripts/am_patch.py",
            "--override",
            "ipc_handshake_enabled=true",
            "--override",
            "ipc_handshake_wait_s=3",
            "500",
        ]
        with patch(
            "patchhub.asgi.async_queue.job_socket_path",
            return_value="/tmp/audiomason/patchhub_job-500.sock",
        ):
            out = _inject_web_overrides(
                argv,
                "job-500",
                ipc_handshake_wait_s=1,
            )

        self.assertEqual(out.count("ipc_handshake_enabled=true"), 1)
        self.assertEqual(out.count("ipc_handshake_wait_s=3"), 1)
        self.assertIn("ipc_socket_enabled=true", out)
        self.assertIn("patch_layout_json_dir=artifacts/web_jobs/job-500", out)
