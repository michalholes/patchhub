"""Issue 219: engine root/path validation and normalization."""

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


def test_invalid_root_is_validation_envelope(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    out = engine.create_session("nope", "x")
    assert isinstance(out, dict)
    err = out.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "VALIDATION_ERROR"


def test_absolute_or_traversal_path_is_validation_envelope(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)

    out_abs = engine.create_session("inbox", "/x")
    err = out_abs.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "VALIDATION_ERROR"

    out_trav = engine.create_session("inbox", "a/../b")
    err2 = out_trav.get("error")
    assert isinstance(err2, dict)
    assert err2.get("code") == "VALIDATION_ERROR"


def test_path_is_normalized(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    # ensure inbox structure exists so discovery runs
    (tmp_path / "inbox" / "a" / "b" / "c").mkdir(parents=True, exist_ok=True)

    out = engine.create_session("inbox", "a//b/./c")
    assert str(out.get("session_id") or "")
    src = out.get("source")
    assert isinstance(src, dict)
    assert src.get("root") == "inbox"
    assert src.get("relative_path") == "a/b/c"
