"""Tests for required import session artifacts (spec 10.7)."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
RootName = import_module("plugins.file_io.service").RootName


def _make_engine(tmp_path: Path):
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
    return ImportWizardEngine(resolver=resolver), roots


def _write_inbox_source_dir(roots: dict[str, Path], rel_dir: str) -> None:
    d = roots["inbox"] / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "file.txt").write_text("x", encoding="utf-8")


def test_create_session_creates_required_subpaths(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_source_dir(roots, "src")

    result = engine.create_session("inbox", "src")

    assert "error" not in result
    sid = result["session_id"]
    base = f"import/sessions/{sid}"

    required = [
        f"{base}/effective_model.json",
        f"{base}/effective_config.json",
        f"{base}/discovery.json",
        f"{base}/state.json",
        f"{base}/decisions.jsonl",
    ]
    for rel in required:
        assert fs.exists(RootName.WIZARDS, rel), rel
