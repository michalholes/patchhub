from __future__ import annotations

from pathlib import Path
from typing import Any

from audiomason.core.context import ProcessingContext
from audiomason.core.events import get_event_bus
from audiomason.core.orchestration import Orchestrator
from audiomason.core.orchestration_models import ProcessRequest


def assert_is_envelope(published_event: str, payload: dict[str, Any]) -> None:
    assert isinstance(payload, dict)
    required = {"event", "component", "operation", "timestamp", "data"}
    assert set(payload.keys()) == required
    assert payload["event"] == published_event
    assert isinstance(payload["component"], str)
    assert isinstance(payload["operation"], str)
    assert isinstance(payload["timestamp"], str)
    assert isinstance(payload["data"], dict)


class _OkPlugin:
    async def process(self, context: ProcessingContext) -> ProcessingContext:
        return context


class _FakePluginLoader:
    def get_plugin(self, name: str) -> Any:
        assert name == "ok"
        return _OkPlugin()


def test_diagnostics_envelope_and_min_event_set(tmp_path: Path) -> None:
    bus = get_event_bus()
    bus.clear()

    published: list[tuple[str, dict[str, Any]]] = []

    def _on_all(event: str, data: dict[str, Any]) -> None:
        published.append((event, data))

    bus.subscribe_all(_on_all)

    pipeline_yaml = tmp_path / "pipeline.yaml"
    yaml_text = (
        "pipeline:\n"
        "  name: test\n"
        "  steps:\n"
        "    - id: s1\n"
        "      plugin: ok\n"
        "      interface: IProcessor\n"
    )
    pipeline_yaml.write_text(yaml_text, encoding="utf-8")

    contexts = [
        ProcessingContext(id="c1", source=tmp_path / "a.m4a"),
        ProcessingContext(id="c2", source=tmp_path / "b.m4a"),
    ]

    orch = Orchestrator()
    req = ProcessRequest(
        contexts=contexts,
        pipeline_path=pipeline_yaml,
        plugin_loader=_FakePluginLoader(),
    )

    _ = orch.start_process(req)

    diag_events = [(ev, data) for (ev, data) in published if ev.startswith("diag.")]
    assert diag_events, "expected some diagnostic events"

    for ev, data in diag_events:
        assert_is_envelope(ev, data)

    names = [ev for ev, _ in diag_events]
    for required in [
        "diag.job.start",
        "diag.job.end",
        "diag.ctx.start",
        "diag.ctx.end",
        "diag.boundary.start",
        "diag.boundary.end",
        "diag.pipeline.start",
        "diag.pipeline.end",
        "diag.pipeline.step.start",
        "diag.pipeline.step.end",
    ]:
        assert required in names

    assert names.count("diag.ctx.start") == 2
    assert names.count("diag.ctx.end") == 2
