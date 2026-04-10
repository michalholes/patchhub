# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_amp import api_amp_schema
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


class TestAmpSchema(unittest.TestCase):
    def test_schema_contains_bootstrap_only_keys(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir(parents=True)
            (root / "scripts" / "am_patch").mkdir(parents=True)
            (root / "scripts" / "am_patch" / "am_patch.toml").write_text(
                'verbosity = "normal"\n', encoding="utf-8"
            )

            dummy = _Dummy(repo_root=root)
            status, data = api_amp_schema(dummy)
            self.assertEqual(status, 200)
            obj = json.loads(data.decode("utf-8"))
            self.assertTrue(obj.get("ok"))
            schema = obj.get("schema")
            self.assertIsInstance(schema, dict)

            self.assertIn("schema_version", schema)
            self.assertIn("policy", schema)

            policy = schema.get("policy")
            self.assertIsInstance(policy, dict)

            self.assertIn("verbosity", policy)
            self.assertIn("console_color", policy)
            self.assertIn("target_repo_name", policy)
            self.assertIn("target_repo_roots", policy)
            self.assertIn("target_repo_config_relpath", policy)
            self.assertIn("gates_order", policy)
            self.assertIn("failure_zip_enabled", policy)
            self.assertIn("patch_script_archive_enabled", policy)
            self.assertIn("success_archive_enabled", policy)
            self.assertIn("artifact_stage_enabled", policy)
            self.assertIn("issue_diff_bundle_enabled", policy)
            self.assertEqual(policy["failure_zip_enabled"].get("type"), "bool")
            self.assertEqual(policy["patch_script_archive_enabled"].get("type"), "bool")
            self.assertEqual(policy["success_archive_enabled"].get("type"), "bool")
            self.assertEqual(policy["artifact_stage_enabled"].get("type"), "bool")
            self.assertEqual(policy["issue_diff_bundle_enabled"].get("type"), "bool")

            self.assertNotIn("json_out", policy)
            self.assertNotIn("pytest_routing_mode", policy)
            self.assertNotIn("pytest_roots", policy)
            self.assertNotIn("pytest_tree", policy)
            self.assertNotIn("pytest_namespace_modules", policy)
            self.assertNotIn("pytest_dependencies", policy)
            self.assertNotIn("pytest_external_dependencies", policy)
            self.assertNotIn("gate_monolith_areas_prefixes", policy)
            self.assertNotIn("gates_skip_biome", policy)
            self.assertNotIn("python_gate_mode", policy)

            verbosity = policy.get("verbosity")
            self.assertIsInstance(verbosity, dict)
            self.assertEqual(verbosity.get("key"), "verbosity")
            self.assertIsInstance(verbosity.get("enum"), list)
