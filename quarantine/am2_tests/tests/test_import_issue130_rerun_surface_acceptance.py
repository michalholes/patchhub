from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from audiomason.core.config import ConfigResolver
from audiomason.core.diagnostics import build_envelope
from audiomason.core.events import get_event_bus

ImportPlugin = import_module("plugins.import.plugin").ImportPlugin
processed_required = import_module("plugins.import.processed_registry_required")
read_json = import_module("plugins.import.storage").read_json
RootName = import_module("plugins.file_io.service").RootName


def _make_plugin(tmp_path: Path) -> tuple[Any, dict[str, Path]]:
    roots = {
        name: tmp_path / name for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
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
    return ImportPlugin(resolver=resolver), roots


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


def test_rerun_and_resume_read_session_finalize_surface_only(tmp_path: Path, monkeypatch) -> None:
    cast(Any, processed_required)._INSTALLED = False
    bus = get_event_bus()
    bus.clear()

    plugin, roots = _make_plugin(tmp_path)
    engine = plugin.get_engine()
    diag_mod = import_module("plugins.import.engine_diagnostics_required")
    monkeypatch.setattr(diag_mod, "submit_process_job", lambda **_kw: None)

    book_dir = roots["inbox"] / "AuthorA" / "Book1"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "track.txt").write_text("x", encoding="utf-8")

    state = engine.create_session(
        "inbox",
        "",
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id
    assert state.get("current_step_id") == "effective_author"
    assert state.get("selected_author_ids")
    assert state.get("selected_book_ids")
    _ = engine.compute_plan(session_id)

    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    state_doc = json.loads(state_path.read_text(encoding="utf-8"))
    state_doc.setdefault("answers", {})["id3_policy"] = {
        "values": {
            "title": "Canonical Edition",
            "artist": "Canonical Author",
            "album": "Canonical Edition",
            "album_artist": "Canonical Author",
        }
    }
    state_doc.setdefault("answers", {})["final_summary_confirm"] = {"confirm_start": True}
    state_doc.setdefault("conflicts", {})["policy"] = "auto"
    state_doc["status"] = "in_progress"
    state_path.write_text(json.dumps(state_doc), encoding="utf-8")

    started = engine.start_processing(session_id, {"confirm": True})
    assert started["batch_size"] == 1
    job_id = started["job_ids"][0]

    bus.publish(
        "diag.job.end",
        build_envelope(
            event="diag.job.end",
            component="jobs",
            operation="run_job",
            data={
                "job_id": job_id,
                "job_type": "process",
                "status": "succeeded",
                "duration_ms": 1,
            },
        ),
    )

    resumed = engine.create_session(
        "inbox",
        "",
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    assert resumed["session_id"] == session_id
    assert resumed["status"] == "succeeded"
    dry_run_rel = (
        f"import/sessions/{session_id}/finalize/AuthorA/Book1/"
        "Canonical Author - Canonical Edition.dryrun.txt"
    )
    log_rel = f"import/sessions/{session_id}/finalize/AuthorA/Book1/processing.log"
    finalize = resumed["computed"]["finalize"]
    assert finalize["job_id"] == job_id
    assert finalize["report_path"] == f"wizards:import/sessions/{session_id}/finalize/report.json"
    report_ref = f"wizards:import/sessions/{session_id}/finalize/report.json"
    assert finalize["artifacts"]["report"] == report_ref
    assert list(finalize["artifacts"]["processing_logs"].values()) == [f"wizards:{log_rel}"]
    assert list(finalize["artifacts"]["dry_run_texts"].values()) == [f"wizards:{dry_run_rel}"]
    assert finalize["counts"] == {"books": 1, "capabilities": 3}
    assert finalize["status"] == "succeeded"

    dry_run_text = (roots["wizards"] / dry_run_rel).read_text(encoding="utf-8")
    assert "title=Canonical Edition" in dry_run_text

    rerun = engine.start_processing(session_id, {"confirm": True})
    assert rerun["job_ids"] == [job_id]
    assert rerun["batch_size"] == 1
    assert rerun["finalize"] == finalize
