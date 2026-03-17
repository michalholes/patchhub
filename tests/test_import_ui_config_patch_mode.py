"""Issue 223: POST /import/ui/config patch mode (Variant B)."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


def _make_engine(tmp_path: Path) -> ImportWizardEngine:
    roots = {
        "inbox": tmp_path / "inbox",
        "stage": tmp_path / "stage",
        "outbox": tmp_path / "outbox",
        "jobs": tmp_path / "jobs",
        "config": tmp_path / "config",
        "wizards": tmp_path / "wizards",
    }
    defaults = {
        "file_io": {
            "roots": {
                "inbox_dir": str(roots["inbox"]),
                "stage_dir": str(roots["stage"]),
                "outbox_dir": str(roots["outbox"]),
                "jobs_dir": str(roots["jobs"]),
                "config_dir": str(roots["config"]),
                "wizards_dir": str(roots["wizards"]),
            }
        },
        "output_dir": str(roots["outbox"]),
        "diagnostics": {"enabled": False},
    }
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver)


def test_patch_mode_sets_fields_atomically(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    before = engine.reset_flow_config()
    assert isinstance(before, dict)
    assert before.get("version") == 1

    out = engine.set_flow_config(
        {
            "mode": "patch",
            "ops": [
                {"op": "set", "path": "steps.optional_step.enabled", "value": True},
            ],
        }
    )
    assert isinstance(out, dict)
    assert "error" not in out
    steps = out.get("steps") or {}
    assert (steps.get("optional_step") or {}).get("enabled") is True

    after = engine.get_flow_config()
    steps_after = after.get("steps") or {}
    assert (steps_after.get("optional_step") or {}).get("enabled") is True


def test_patch_mode_rejects_unknown_path(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    _ = engine.reset_flow_config()
    out = engine.set_flow_config(
        {"mode": "patch", "ops": [{"op": "set", "path": "nope", "value": 1}]}
    )
    err = out.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "VALIDATION_ERROR"


def test_patch_mode_rejects_type_mismatch(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    _ = engine.reset_flow_config()
    out = engine.set_flow_config(
        {
            "mode": "patch",
            "ops": [
                {
                    "op": "set",
                    "path": "steps.optional_step.enabled",
                    "value": 123,
                }
            ],
        }
    )
    err = out.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "VALIDATION_ERROR"


def test_patch_mode_rejects_unknown_op(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    _ = engine.reset_flow_config()
    out = engine.set_flow_config(
        {
            "mode": "patch",
            "ops": [
                {
                    "op": "add",
                    "path": "steps.optional_step.enabled",
                    "value": True,
                }
            ],
        }
    )
    err = out.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "VALIDATION_ERROR"


def test_patch_mode_rejects_empty_ops(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    _ = engine.reset_flow_config()
    out = engine.set_flow_config({"mode": "patch", "ops": []})
    err = out.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "VALIDATION_ERROR"
