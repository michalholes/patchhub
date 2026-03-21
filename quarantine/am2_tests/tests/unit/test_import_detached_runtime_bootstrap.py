from __future__ import annotations

import json
import os
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from audiomason.core.config import ConfigResolver
from audiomason.core.jobs.model import JobState
from audiomason.core.orchestration import Orchestrator
from audiomason.core.process_contract_runtime import (
    reset_process_contract_runtime_for_tests,
)

ImportPlugin = import_module("plugins.import.plugin").ImportPlugin
RootName = import_module("plugins.file_io.service").RootName


@pytest.fixture(autouse=True)
def _reset_process_contract_runtime() -> None:
    reset_process_contract_runtime_for_tests()
    yield
    reset_process_contract_runtime_for_tests()


def _wait_for_terminal_job(job_id: str) -> JobState:
    orch = Orchestrator()
    import time

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        job = orch.get_job(job_id)
        if job.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            return job.state
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for terminal state: {job_id}")


class _FakeAudioProcessor:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.bitrate = "128k"
        self.loudnorm = False
        self.split_chapters = False

    def plan_import_conversion(
        self,
        source: Path,
        output_dir: Path,
        *,
        chapters: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        del chapters
        self.calls.append(f"audio.plan:{source.name}")
        return [{"source": source, "output": output_dir / f"{source.stem}.mp3", "order": 1}]

    async def _execute_plan(self, plan: list[dict[str, Any]]) -> list[Path]:
        outputs: list[Path] = []
        for item in plan:
            output = Path(item["output"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"mp3")
            outputs.append(output)
            self.calls.append(f"audio.exec:{output.name}")
        return outputs


class _FakeCoverHandler:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def apply_cover_candidate(
        self,
        candidate: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> Path | None:
        self.calls.append(f"cover.apply:{candidate.get('candidate_id')}")
        if output_dir is None:
            return None
        output = output_dir / "cover.jpg"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"jpg")
        return output

    async def convert_to_jpeg(self, image_path: Path, quality: int = 95) -> Path:
        del quality
        self.calls.append("cover.convert")
        return image_path

    async def embed_covers_batch(self, mp3_files: list[Path], cover_path: Path) -> None:
        del cover_path
        self.calls.append("cover.embed")
        for mp3_file in mp3_files:
            mp3_file.write_bytes(mp3_file.read_bytes() + b"|cover")


class _FakeID3Tagger:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def write_tags(
        self,
        mp3_file: Path,
        tags: dict[str, Any],
        *,
        wipe_before_write: bool = True,
        preserve_cover: bool = True,
        file_index: int = 0,
    ) -> None:
        del wipe_before_write, preserve_cover, file_index
        values = dict(tags.get("values") or {}) if isinstance(tags, dict) else {}
        self.calls.append("tags.write:" + mp3_file.name + ":" + str(values.get("title") or ""))
        mp3_file.write_bytes(mp3_file.read_bytes() + b"|tags")


class _FakeLoader:
    def __init__(self, import_plugin: Any, calls: list[str]) -> None:
        self._plugins = {
            "import": import_plugin,
            "audio_processor": _FakeAudioProcessor(calls),
            "cover_handler": _FakeCoverHandler(calls),
            "id3_tagger": _FakeID3Tagger(calls),
        }

    def get_plugin(self, name: str) -> Any:
        return self._plugins[name]


def _roots(base: Path, *, prefix: str) -> dict[str, Path]:
    roots = {
        "inbox": base / f"{prefix}_inbox",
        "stage": base / f"{prefix}_stage",
        "outbox": base / f"{prefix}_outbox",
        "jobs": base / f"{prefix}_jobs",
        "config": base / f"{prefix}_config",
        "wizards": base / f"{prefix}_wizards",
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return roots


def _resolver_for_roots(tmp_path: Path, roots: dict[str, Path]) -> ConfigResolver:
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
    return ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / f"{roots['wizards'].name}_user.yaml",
        system_config_path=tmp_path / f"{roots['wizards'].name}_system.yaml",
    )


def _make_plugin(tmp_path: Path, roots: dict[str, Path]) -> Any:
    return ImportPlugin(resolver=_resolver_for_roots(tmp_path, roots))


def _disable_optional_steps() -> dict[str, object]:
    return {
        "steps": {
            "filename_policy": {"enabled": False},
            "covers_policy": {"enabled": False},
            "id3_policy": {"enabled": False},
            "audio_processing": {"enabled": False},
            "publish_policy": {"enabled": False},
            "delete_source_policy": {"enabled": False},
            "parallelism": {"enabled": False},
        }
    }


def _write_inbox_book(roots: dict[str, Path]) -> None:
    book_dir = roots["inbox"] / "AuthorA" / "Book1"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "track01.m4a").write_bytes(b"audio")


def _mutate_state_for_finalize(roots: dict[str, Path], session_id: str) -> None:
    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("answers", {})["final_summary_confirm"] = {"confirm_start": True}
    state.setdefault("conflicts", {})["policy"] = "auto"
    state["status"] = "in_progress"
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _prepare_pending_process_job(
    tmp_path: Path,
    monkeypatch,
) -> tuple[Any, dict[str, Path], str, str, dict[str, Any]]:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    roots = _roots(tmp_path, prefix="host")
    plugin = _make_plugin(tmp_path, roots)
    diag_mod = import_module("plugins.import.engine_diagnostics_required")
    monkeypatch.setattr(diag_mod, "submit_process_job", lambda **_kw: None)

    _write_inbox_book(roots)
    engine = plugin.get_engine()
    state = engine.create_session(
        "inbox",
        "",
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id
    _ = engine.compute_plan(session_id)
    _mutate_state_for_finalize(roots, session_id)
    started = engine.start_processing(session_id, {"confirm": True})
    job_ids = started.get("job_ids")
    assert isinstance(job_ids, list) and len(job_ids) == 1
    job_id = str(job_ids[0])

    job_requests_path = roots["wizards"] / "import" / "sessions" / session_id / "job_requests.json"
    job_requests = json.loads(job_requests_path.read_text(encoding="utf-8"))
    return plugin, roots, session_id, job_id, job_requests


def test_canonical_job_requests_persist_detached_runtime_bootstrap(
    tmp_path: Path, monkeypatch
) -> None:
    _plugin, roots, _session_id, _job_id, job_requests = _prepare_pending_process_job(
        tmp_path, monkeypatch
    )

    detached_runtime = dict(job_requests.get("detached_runtime") or {})
    file_io = dict(detached_runtime.get("file_io") or {})
    bootstrap_roots = dict(file_io.get("roots") or {})

    assert bootstrap_roots == {
        "inbox_dir": str(roots["inbox"]),
        "stage_dir": str(roots["stage"]),
        "jobs_dir": str(roots["jobs"]),
        "outbox_dir": str(roots["outbox"]),
        "config_dir": str(roots["config"]),
        "wizards_dir": str(roots["wizards"]),
    }


def test_pending_process_job_adopts_detached_runtime_without_original_host_engine(
    tmp_path: Path, monkeypatch
) -> None:
    _host_plugin, roots, session_id, job_id, job_requests = _prepare_pending_process_job(
        tmp_path, monkeypatch
    )

    detached_roots = _roots(tmp_path, prefix="detached")
    detached_roots["wizards"] = roots["wizards"]
    detached_plugin = _make_plugin(tmp_path, detached_roots)

    detached_fs = detached_plugin.get_engine().get_file_service()
    assert detached_fs.root_dir(RootName.STAGE) == detached_roots["stage"]
    assert detached_fs.root_dir(RootName.STAGE) != roots["stage"]

    cwd = tmp_path / "cwd_elsewhere"
    cwd.mkdir(parents=True, exist_ok=True)
    old_cwd = Path.cwd()
    calls: list[str] = []
    try:
        os.chdir(cwd)
        loader = _FakeLoader(detached_plugin, calls)
        orch = Orchestrator()
        orch.run_job(job_id, plugin_loader=loader)
    finally:
        os.chdir(old_cwd)

    assert _wait_for_terminal_job(job_id) == JobState.SUCCEEDED

    first_action = dict(job_requests["actions"][0])
    target = dict(first_action["target"])
    target_rel = str(target["relative_path"])
    actual_output = roots["stage"] / target_rel / "track01.mp3"
    detached_output = detached_roots["stage"] / target_rel / "track01.mp3"

    assert actual_output.exists()
    assert actual_output.read_bytes().endswith(b"|tags")
    assert not detached_output.exists()
    assert calls == [
        "audio.plan:track01.m4a",
        "audio.exec:track01.mp3",
        "cover.apply:embedded:track01.m4a",
        "cover.convert",
        "cover.embed",
        "tags.write:track01.mp3:Book1",
    ]
    assert session_id == str(job_requests.get("session_id") or "")
