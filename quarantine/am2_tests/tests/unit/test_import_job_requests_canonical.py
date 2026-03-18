"""Import plugin: canonical job_requests.json stability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine


@dataclass(frozen=True)
class _Job:
    job_id: str


def _make_engine(tmp_path: Path) -> tuple[Any, dict[str, Path]]:
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
    cli_args = defaults
    resolver = ConfigResolver(
        cli_args=cli_args,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver), roots


def _write_inbox_source_dir(roots: dict[str, Path], rel_dir: str) -> None:
    d = roots["inbox"] / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "file.txt").write_text("x", encoding="utf-8")


def _mutate_state_for_finalize(roots: dict[str, Path], session_id: str) -> None:
    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("inputs", {})["final_summary_confirm"] = {"confirm_start": True}
    state.setdefault("conflicts", {})["policy"] = "ask"
    state["status"] = "in_progress"
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_job_requests_json_is_byte_stable(monkeypatch, tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    rel = "book6"
    _write_inbox_source_dir(roots, rel)

    state = engine.create_session("inbox", rel, mode="stage")
    session_id = str(state.get("session_id") or "")
    assert session_id
    _mutate_state_for_finalize(roots, session_id)

    from audiomason.core.jobs import api as jobs_api

    def _create_job(self, job_type, *, meta):
        return _Job(job_id="job-456")

    monkeypatch.setattr(jobs_api.JobService, "create_job", _create_job)
    diag_mod = import_module("plugins.import.engine_diagnostics_required")
    monkeypatch.setattr(diag_mod, "submit_process_job", lambda **_kw: None)

    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    job_path = session_dir / "job_requests.json"

    _ = engine.start_processing(session_id, {"confirm": True})
    b1 = job_path.read_bytes()

    _ = engine.start_processing(session_id, {"confirm": True})
    b2 = job_path.read_bytes()

    assert b1 == b2
