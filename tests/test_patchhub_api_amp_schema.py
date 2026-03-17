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
    def test_schema_contains_expected_keys(self) -> None:
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
            self.assertIn("pytest_routing_mode", policy)
            self.assertIn("pytest_full_suite_prefixes", policy)

            self.assertNotIn("json_out", policy)
            self.assertNotIn("pytest_roots", policy)
            self.assertNotIn("pytest_tree", policy)
            self.assertNotIn("pytest_namespace_modules", policy)
            self.assertNotIn("pytest_dependencies", policy)
            self.assertNotIn("pytest_external_dependencies", policy)

            self.assertIn("gate_monolith_areas_prefixes", policy)
            self.assertIn("gate_monolith_areas_names", policy)
            self.assertIn("gate_monolith_areas_dynamic", policy)

            # Variant B file-scoped gates
            self.assertIn("gates_skip_biome", policy)
            self.assertIn("gate_biome_extensions", policy)
            self.assertIn("gate_biome_command", policy)
            self.assertIn("gates_skip_typescript", policy)
            self.assertIn("gate_typescript_extensions", policy)
            self.assertIn("gate_typescript_command", policy)

            verbosity = policy.get("verbosity")
            self.assertIsInstance(verbosity, dict)
            self.assertEqual(verbosity.get("key"), "verbosity")
            self.assertIsInstance(verbosity.get("enum"), list)
