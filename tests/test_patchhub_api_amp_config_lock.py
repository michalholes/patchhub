# ruff: noqa: E402
from __future__ import annotations

import fcntl
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_amp import api_amp_config_post
from patchhub.fs_jail import FsJail


class _Dummy:
    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.cfg = SimpleNamespace(
            runner=SimpleNamespace(runner_config_toml="scripts/am_patch/am_patch.toml")
        )
        self.jail = FsJail(
            repo_root=repo_root,
            patches_root_rel="patches",
            crud_allowlist=[""],
            allow_crud=True,
        )


class TestAmpConfigLock(unittest.TestCase):
    def test_save_rejected_when_lock_held(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir(parents=True)
            (root / "scripts" / "am_patch").mkdir(parents=True)
            (root / "scripts" / "am_patch" / "am_patch.toml").write_text(
                'verbosity = "normal"\n', encoding="utf-8"
            )

            dummy = _Dummy(repo_root=root)
            lock_path = dummy.jail.lock_path()
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+") as fd:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                status, data = api_amp_config_post(
                    dummy, {"values": {"verbosity": "quiet"}, "dry_run": False}
                )
                self.assertEqual(status, 409)
                obj = json.loads(data.decode("utf-8"))
                self.assertFalse(obj.get("ok"))
