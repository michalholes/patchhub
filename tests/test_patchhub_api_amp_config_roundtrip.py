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

from patchhub.app_api_amp import api_amp_config_get, api_amp_config_post, api_amp_schema
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


class TestAmpConfigRoundtrip(unittest.TestCase):
    def _ui_payload(self, schema: dict, values: dict) -> dict:
        payload: dict[str, object] = {}
        policy = schema.get("policy", {})
        self.assertIsInstance(policy, dict)
        for key, item in policy.items():
            self.assertIsInstance(item, dict)
            type_name = str(item.get("type") or "")
            value = values.get(key)
            if type_name == "list[str]":
                payload[key] = [
                    "" if part is None else str(part)
                    for part in (value if isinstance(value, list) else [])
                ]
            elif type_name == "bool":
                payload[key] = bool(value)
            elif type_name == "int":
                payload[key] = value if isinstance(value, int) else 0
            else:
                payload[key] = "" if value is None else str(value)
        return payload

    def test_get_validate_save_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "patches").mkdir(parents=True)
            (root / "scripts" / "am_patch").mkdir(parents=True)

            repo_cfg_path = (
                Path(__file__).resolve().parents[1] / "scripts" / "am_patch" / "am_patch.toml"
            )
            cfg_path = root / "scripts" / "am_patch" / "am_patch.toml"
            cfg_path.write_text(repo_cfg_path.read_text(encoding="utf-8"), encoding="utf-8")

            dummy = _Dummy(repo_root=root)

            st_schema, data_schema = api_amp_schema(dummy)
            self.assertEqual(st_schema, 200)
            schema_obj = json.loads(data_schema.decode("utf-8"))
            self.assertTrue(schema_obj.get("ok"))
            schema = schema_obj.get("schema", {})
            policy = schema.get("policy", {})
            self.assertIsInstance(policy, dict)
            self.assertNotIn("json_out", policy)
            self.assertNotIn("pytest_roots", policy)
            self.assertNotIn("pytest_dependencies", policy)
            self.assertIn("gate_monolith_areas_prefixes", policy)
            self.assertIn("gate_monolith_areas_names", policy)
            self.assertIn("gate_monolith_areas_dynamic", policy)

            st1, data1 = api_amp_config_get(dummy)
            self.assertEqual(st1, 200)
            obj1 = json.loads(data1.decode("utf-8"))
            self.assertTrue(obj1.get("ok"))
            self.assertEqual(obj1.get("values", {}).get("verbosity"), "normal")

            payload = self._ui_payload(schema, obj1.get("values", {}))
            self.assertEqual(
                payload.get("gate_monolith_areas_dynamic"),
                ["", "", "plugins.<name>", "", ""],
            )

            st2, data2 = api_amp_config_post(dummy, {"values": payload, "dry_run": True})
            self.assertEqual(st2, 200)
            obj2 = json.loads(data2.decode("utf-8"))
            self.assertTrue(obj2.get("ok"))
            self.assertTrue(obj2.get("dry_run"))
            self.assertEqual(
                obj2.get("values", {}).get("gate_monolith_areas_dynamic"),
                ["", "", "plugins.<name>", "", ""],
            )
            self.assertIn('verbosity = "normal"', cfg_path.read_text(encoding="utf-8"))

            payload["verbosity"] = "quiet"
            payload["pytest_routing_mode"] = "legacy"
            payload["pytest_full_suite_prefixes"] = ["pyproject.toml"]
            st3, data3 = api_amp_config_post(dummy, {"values": payload, "dry_run": False})
            self.assertEqual(st3, 200)
            obj3 = json.loads(data3.decode("utf-8"))
            self.assertTrue(obj3.get("ok"))
            self.assertFalse(obj3.get("dry_run"))

            st4, data4 = api_amp_config_get(dummy)
            self.assertEqual(st4, 200)
            obj4 = json.loads(data4.decode("utf-8"))
            self.assertTrue(obj4.get("ok"))
            self.assertEqual(obj4.get("values", {}).get("verbosity"), "quiet")
            self.assertEqual(obj4.get("values", {}).get("pytest_routing_mode"), "legacy")
            self.assertEqual(
                obj4.get("values", {}).get("pytest_full_suite_prefixes"),
                ["pyproject.toml"],
            )
            self.assertEqual(
                obj4.get("values", {}).get("gate_monolith_areas_dynamic"),
                ["", "", "plugins.<name>", "", ""],
            )
