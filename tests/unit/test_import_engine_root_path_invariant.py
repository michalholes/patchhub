"""Root/path invariant validation for ImportWizardEngine.create_session."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, dict[str, Path]]:
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


def test_create_session_rejects_missing_root(tmp_path: Path) -> None:
    engine, _roots = _make_engine(tmp_path)
    out = engine.create_session("", "src")
    assert out["error"]["code"] == "VALIDATION_ERROR"
    assert out["error"]["details"][0]["path"] == "$.root"


def test_create_session_rejects_invalid_root(tmp_path: Path) -> None:
    engine, _roots = _make_engine(tmp_path)
    out = engine.create_session("nope", "src")
    assert out["error"]["code"] == "VALIDATION_ERROR"
    assert out["error"]["details"][0]["path"] == "$.root"


def test_create_session_rejects_absolute_path(tmp_path: Path) -> None:
    engine, _roots = _make_engine(tmp_path)
    out = engine.create_session("inbox", "/etc")
    assert out["error"]["code"] == "VALIDATION_ERROR"
    assert out["error"]["details"][0]["path"] == "$.relative_path"


def test_create_session_rejects_traversal(tmp_path: Path) -> None:
    engine, _roots = _make_engine(tmp_path)
    out = engine.create_session("inbox", "../x")
    assert out["error"]["code"] == "VALIDATION_ERROR"
    assert out["error"]["details"][0]["path"] == "$.relative_path"


def test_create_session_accepts_normalized_relative_path(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    (roots["inbox"] / "src").mkdir(parents=True, exist_ok=True)
    out = engine.create_session("inbox", "./src//")
    assert "error" not in out
    assert out.get("session_id")
    src = out.get("source") or {}
    assert src.get("relative_path") == "src"


def test_create_session_allows_empty_relative_path(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    roots["inbox"].mkdir(parents=True, exist_ok=True)
    out = engine.create_session("inbox", "")
    assert "error" not in out
    assert out.get("session_id")
    src = out.get("source") or {}
    assert src.get("relative_path") in {"", None}
