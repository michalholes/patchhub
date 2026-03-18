from __future__ import annotations

import json
from pathlib import Path

from audiomason.core.config import ConfigResolver
from audiomason.core.diagnostics import install_jsonl_sink
from audiomason.core.events import get_event_bus


def _reset_bus_and_sink() -> None:
    bus = get_event_bus()
    bus.clear()
    # Reset module-level idempotency guard.
    import audiomason.core.diagnostics as diagnostics

    diagnostics._SINK_INSTALLED = False  # type: ignore[attr-defined]


def test_subscribe_all_receives_events() -> None:
    _reset_bus_and_sink()
    bus = get_event_bus()

    seen: list[tuple[str, dict[str, object]]] = []

    def cb(event: str, data: dict[str, object]) -> None:
        seen.append((event, data))

    bus.subscribe_all(cb)
    bus.publish("any_event", {"x": 1})

    assert seen == [("any_event", {"x": 1})]


def test_disabled_does_not_create_jsonl(tmp_path: Path) -> None:
    _reset_bus_and_sink()

    resolver = ConfigResolver(
        cli_args={"stage_dir": str(tmp_path)},
        user_config_path=tmp_path / "user_config.yaml",
        system_config_path=tmp_path / "system_config.yaml",
    )
    install_jsonl_sink(resolver=resolver)

    get_event_bus().publish("evt", {"k": "v"})

    out_path = tmp_path / "diagnostics" / "diagnostics.jsonl"
    assert not out_path.exists()


def test_enabled_writes_jsonl_and_wraps_non_envelope(tmp_path: Path) -> None:
    _reset_bus_and_sink()

    resolver = ConfigResolver(
        cli_args={"stage_dir": str(tmp_path), "diagnostics": {"enabled": True}},
    )
    install_jsonl_sink(resolver=resolver)

    # Envelope-like event (exact keys, data is dict).
    get_event_bus().publish(
        "diag.envelope",
        {
            "event": "diag.envelope",
            "component": "core",
            "operation": "op",
            "timestamp": "2026-02-11T00:00:00Z",
            "data": {"a": 1},
        },
    )

    # Non-envelope event should be wrapped.
    get_event_bus().publish("plain", {"b": 2})

    out_path = tmp_path / "diagnostics" / "diagnostics.jsonl"
    assert out_path.exists()

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    obj0 = json.loads(lines[0])
    obj1 = json.loads(lines[1])

    assert set(obj0.keys()) == {"component", "data", "event", "operation", "timestamp"}
    assert obj0["component"] == "core"
    assert obj0["data"] == {"a": 1}

    assert set(obj1.keys()) == {"component", "data", "event", "operation", "timestamp"}
    assert obj1["event"] == "plain"
    assert obj1["component"] == "unknown"
    assert obj1["operation"] == "unknown"
    assert obj1["data"] == {"b": 2}


def test_install_is_idempotent(tmp_path: Path) -> None:
    _reset_bus_and_sink()

    resolver = ConfigResolver(
        cli_args={"stage_dir": str(tmp_path), "diagnostics": {"enabled": True}},
    )

    install_jsonl_sink(resolver=resolver)
    install_jsonl_sink(resolver=resolver)

    get_event_bus().publish("once", {"x": 1})

    out_path = tmp_path / "diagnostics" / "diagnostics.jsonl"
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
