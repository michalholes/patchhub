"""Required diagnostics fields must be present on mandatory events (spec 10.14)."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver
from audiomason.core.events import get_event_bus

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


def test_mandatory_events_have_required_fields(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    (roots["inbox"] / "src").mkdir(parents=True, exist_ok=True)

    bus = get_event_bus()
    seen: dict[str, dict] = {}

    def _mk_cb(name: str):
        def _cb(payload: dict) -> None:
            seen[name] = payload

        return _cb

    cbs = {name: _mk_cb(name) for name in ("model.load", "model.validate", "session.start")}
    for name, cb in cbs.items():
        bus.subscribe(name, cb)

    try:
        state = engine.create_session("inbox", "src")
        assert "error" not in state
    finally:
        for name, cb in cbs.items():
            bus.unsubscribe(name, cb)

    required = {
        "session_id",
        "model_fingerprint",
        "discovery_fingerprint",
        "effective_config_fingerprint",
    }

    assert set(seen.keys()) == {"model.load", "model.validate", "session.start"}
    for env in seen.values():
        assert isinstance(env, dict)
        data = env.get("data")
        assert isinstance(data, dict)
        assert required.issubset(set(data.keys()))
        for k in required:
            assert isinstance(data.get(k), str) and data.get(k)
