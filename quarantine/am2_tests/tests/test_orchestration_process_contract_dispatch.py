from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest
from audiomason.core.context import ProcessingContext
from audiomason.core.jobs.model import JobState, JobType
from audiomason.core.orchestration import Orchestrator
from audiomason.core.orchestration_models import ProcessRequest
from audiomason.core.process_contract_runtime import (
    reset_process_contract_runtime_for_tests,
)
from audiomason.core.process_job_contracts import IMPORT_PROCESS_CONTRACT_ID


class _FakeImportPlugin:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.delay = delay

    async def run_process_contract(
        self, *, job_id: str, job_meta: dict[str, str], plugin_loader: Any
    ) -> None:
        if self.delay > 0.0:
            await asyncio.sleep(self.delay)
        self.calls.append(
            {
                "job_id": job_id,
                "job_meta": dict(job_meta),
                "plugin_loader": plugin_loader,
            }
        )


class _FakeLoader:
    def __init__(self, plugin: _FakeImportPlugin) -> None:
        self._plugin = plugin

    def get_plugin(self, name: str) -> Any:
        assert name == "import"
        return self._plugin


def _write_empty_pipeline(path: Path) -> None:
    path.write_text(
        """pipeline:\n  name: empty\n  description: empty pipeline for tests\n  steps: []\n""",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _reset_process_contract_runtime() -> None:
    reset_process_contract_runtime_for_tests()
    yield
    reset_process_contract_runtime_for_tests()


def _wait_for_terminal_state(orchestrator: Orchestrator, job_id: str) -> Any:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        job = orchestrator.get_job(job_id)
        if job.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for terminal state: {job_id}")


def test_run_job_dispatches_contract_process_to_plugin_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    orchestrator = Orchestrator()
    plugin = _FakeImportPlugin()
    loader = _FakeLoader(plugin)

    job = orchestrator.jobs.create_job(
        JobType.PROCESS,
        meta={
            "contract_id": IMPORT_PROCESS_CONTRACT_ID,
            "job_requests_path": "wizards:import/sessions/s1/job_requests.json",
            "session_id": "s1",
            "cover_policy": "embedded",
        },
    )

    orchestrator.run_job(job.job_id, plugin_loader=loader)

    stored = _wait_for_terminal_state(orchestrator, job.job_id)
    assert stored.state == JobState.SUCCEEDED
    assert plugin.calls == [
        {
            "job_id": job.job_id,
            "job_meta": {
                "contract_id": IMPORT_PROCESS_CONTRACT_ID,
                "job_requests_path": "wizards:import/sessions/s1/job_requests.json",
                "verbosity_override": "1",
            },
            "plugin_loader": loader,
        }
    ]


def test_run_job_rejects_incomplete_process_contract_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    orchestrator = Orchestrator()
    plugin = _FakeImportPlugin()
    loader = _FakeLoader(plugin)

    job = orchestrator.jobs.create_job(
        JobType.PROCESS,
        meta={"contract_id": IMPORT_PROCESS_CONTRACT_ID},
    )

    with pytest.raises(RuntimeError, match="unsupported or incomplete process contract"):
        orchestrator.run_job(job.job_id, plugin_loader=loader)

    stored = orchestrator.get_job(job.job_id)
    assert stored.state == JobState.PENDING
    assert plugin.calls == []


def test_run_job_preserves_legacy_pipeline_dispatch_without_contract_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    pipelines_dir = tmp_path / "pipelines"
    pipelines_dir.mkdir(parents=True, exist_ok=True)
    pipeline_path = pipelines_dir / "empty.yaml"
    _write_empty_pipeline(pipeline_path)

    src = tmp_path / "input.mp3"
    src.write_bytes(b"dummy")

    ctx = ProcessingContext(id="ctx1", source=src)
    orchestrator = Orchestrator()

    req = ProcessRequest(contexts=[ctx], pipeline_path=pipeline_path, plugin_loader=None)
    job_id = orchestrator.start_process(req)

    job = orchestrator.get_job(job_id)
    assert job.state == JobState.SUCCEEDED
    assert job.progress == 1.0


def test_start_process_runtime_adopts_pending_contract_job_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    orchestrator = Orchestrator()
    plugin = _FakeImportPlugin()
    loader = _FakeLoader(plugin)

    job = orchestrator.jobs.create_job(
        JobType.PROCESS,
        meta={
            "contract_id": IMPORT_PROCESS_CONTRACT_ID,
            "job_requests_path": "wizards:import/sessions/s1/job_requests.json",
        },
    )

    waiting = orchestrator.get_job(job.job_id)
    assert waiting.state == JobState.PENDING

    orchestrator.start_process_runtime(plugin_loader=loader)
    orchestrator.start_process_runtime(plugin_loader=loader)

    stored = _wait_for_terminal_state(orchestrator, job.job_id)
    assert stored.state == JobState.SUCCEEDED
    assert len(plugin.calls) == 1
    assert plugin.calls[0]["job_id"] == job.job_id


def test_run_job_starts_runtime_without_adopting_other_pending_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    orchestrator = Orchestrator()
    plugin = _FakeImportPlugin(delay=0.05)
    loader = _FakeLoader(plugin)

    target = orchestrator.jobs.create_job(
        JobType.PROCESS,
        meta={
            "contract_id": IMPORT_PROCESS_CONTRACT_ID,
            "job_requests_path": "wizards:import/sessions/target/job_requests.json",
        },
    )
    other = orchestrator.jobs.create_job(
        JobType.PROCESS,
        meta={
            "contract_id": IMPORT_PROCESS_CONTRACT_ID,
            "job_requests_path": "wizards:import/sessions/other/job_requests.json",
        },
    )

    orchestrator.run_job(target.job_id, plugin_loader=loader)

    stored_target = _wait_for_terminal_state(orchestrator, target.job_id)
    stored_other = orchestrator.get_job(other.job_id)

    assert stored_target.state == JobState.SUCCEEDED
    assert stored_other.state == JobState.PENDING
    assert [call["job_id"] for call in plugin.calls] == [target.job_id]


def test_run_job_survives_async_host_loop_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    orchestrator = Orchestrator()
    plugin = _FakeImportPlugin(delay=0.1)
    loader = _FakeLoader(plugin)

    job = orchestrator.jobs.create_job(
        JobType.PROCESS,
        meta={
            "contract_id": IMPORT_PROCESS_CONTRACT_ID,
            "job_requests_path": "wizards:import/sessions/s1/job_requests.json",
        },
    )

    async def _submit() -> None:
        orchestrator.run_job(job.job_id, plugin_loader=loader)

    asyncio.run(_submit())

    stored = _wait_for_terminal_state(orchestrator, job.job_id)
    assert stored.state == JobState.SUCCEEDED
    assert len(plugin.calls) == 1
