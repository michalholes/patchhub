"""Issue 219: diagnostics payload must include required context."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


@dataclass
class _Bus:
    events: list[tuple[str, dict[str, object]]]

    def __init__(self) -> None:
        self.events = []

    def publish(self, event: str, payload: dict[str, object]) -> None:
        self.events.append((event, payload))


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, _Bus, object]:
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
    bus = _Bus()
    engine_mod = import_module("plugins.import.engine")
    orig = engine_mod.get_event_bus  # type: ignore[attr-defined]
    engine_mod.get_event_bus = lambda: bus  # type: ignore[assignment]
    return ImportWizardEngine(resolver=resolver), bus, orig


def _event_data(payload: dict[str, object]) -> dict[str, object]:
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def test_session_events_include_required_context(tmp_path: Path) -> None:
    engine, bus, orig = _make_engine(tmp_path)

    try:
        # create source content
        (tmp_path / "inbox" / "s").mkdir(parents=True, exist_ok=True)
        (tmp_path / "inbox" / "s" / "x.txt").write_text("x", encoding="utf-8")

        state = engine.create_session("inbox", "s")
        session_id = str(state.get("session_id") or "")
        assert session_id

        assert bus.events
        for _event, payload in bus.events:
            data = _event_data(payload)
            assert data.get("session_id") == session_id
            assert str(data.get("model_fingerprint") or "")
            assert str(data.get("discovery_fingerprint") or "")
            assert str(data.get("effective_config_fingerprint") or "")
    finally:
        engine_mod = import_module("plugins.import.engine")
        engine_mod.get_event_bus = orig  # type: ignore[assignment]
