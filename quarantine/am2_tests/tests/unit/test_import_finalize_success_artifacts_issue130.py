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


def _write_inbox_books(roots: dict[str, Path]) -> None:
    for book in ("Book1", "Book2"):
        book_dir = roots["inbox"] / "AuthorA" / book
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / "track.txt").write_text(book, encoding="utf-8")


def _mutate_state_for_finalize(roots: dict[str, Path], session_id: str, *, policy: str) -> None:
    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("answers", {})["id3_policy"] = {
        "values": {
            "title": "Canonical Edition",
            "artist": "Canonical Author",
            "album": "Canonical Edition",
            "album_artist": "Canonical Author",
        }
    }
    state.setdefault("answers", {})["final_summary_confirm"] = {"confirm_start": True}
    state.setdefault("conflicts", {})["policy"] = policy
    state["status"] = "in_progress"
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _start_processing(plugin: Any, roots: dict[str, Path], monkeypatch) -> tuple[str, str]:
    engine = plugin.get_engine()
    diag_mod = import_module("plugins.import.engine_diagnostics_required")
    monkeypatch.setattr(diag_mod, "submit_process_job", lambda **_kw: None)
    _write_inbox_books(roots)
    state = engine.create_session(
        "inbox",
        "",
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id
    assert state.get("current_step_id") == "select_books"
    step1 = engine.submit_step(session_id, "select_books", {"selection": "all"})
    assert "error" not in step1
    _ = engine.compute_plan(session_id)
    _mutate_state_for_finalize(roots, session_id, policy="auto")
    started = engine.start_processing(session_id, {"confirm": True})
    job_ids = started.get("job_ids")
    assert isinstance(job_ids, list) and len(job_ids) == 1
    return session_id, str(job_ids[0])


def test_finalize_success_artifacts_and_ignore_registry_are_success_only(
    tmp_path: Path, monkeypatch
) -> None:
    cast(Any, processed_required)._INSTALLED = False
    bus = get_event_bus()
    bus.clear()

    plugin, roots = _make_plugin(tmp_path)
    session_id, job_id = _start_processing(plugin, roots, monkeypatch)
    fs = plugin.get_engine().get_file_service()

    report_rel = f"import/sessions/{session_id}/finalize/report.json"
    book1_log_rel = f"import/sessions/{session_id}/finalize/AuthorA/Book1/processing.log"
    book2_log_rel = f"import/sessions/{session_id}/finalize/AuthorA/Book2/processing.log"
    book1_dry_run_rel = (
        f"import/sessions/{session_id}/finalize/AuthorA/Book1/"
        "Canonical Author - Canonical Edition.dryrun.txt"
    )
    book2_dry_run_rel = (
        f"import/sessions/{session_id}/finalize/AuthorA/Book2/"
        "Canonical Author - Canonical Edition.dryrun.txt"
    )
    ignore_rel = "import/processed/ignore_registry.json"

    bus.publish(
        "diag.job.end",
        build_envelope(
            event="diag.job.end",
            component="jobs",
            operation="run_job",
            data={
                "job_id": job_id,
                "job_type": "process",
                "status": "failed",
                "duration_ms": 1,
            },
        ),
    )

    assert not fs.exists(RootName.WIZARDS, report_rel)
    assert not fs.exists(RootName.WIZARDS, book1_log_rel)
    assert not fs.exists(RootName.WIZARDS, book1_dry_run_rel)
    assert not fs.exists(RootName.WIZARDS, ignore_rel)

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

    report = read_json(fs, RootName.WIZARDS, report_rel)
    ignore_registry = read_json(fs, RootName.WIZARDS, ignore_rel)
    state = read_json(fs, RootName.WIZARDS, f"import/sessions/{session_id}/state.json")

    assert report["status"] == "succeeded"
    assert report["counts"] == {"books": 2, "capabilities": 6}
    assert report["artifacts"]["report"] == f"wizards:{report_rel}"
    report_books = {book["source"]["relative_path"]: book["book_id"] for book in report["books"]}
    assert report["artifacts"]["processing_logs"] == {
        report_books["AuthorA/Book1"]: f"wizards:{book1_log_rel}",
        report_books["AuthorA/Book2"]: f"wizards:{book2_log_rel}",
    }
    assert report["artifacts"]["dry_run_texts"] == {
        report_books["AuthorA/Book1"]: f"wizards:{book1_dry_run_rel}",
        report_books["AuthorA/Book2"]: f"wizards:{book2_dry_run_rel}",
    }
    assert [book["source"]["relative_path"] for book in report["books"]] == [
        "AuthorA/Book1",
        "AuthorA/Book2",
    ]
    assert report["books"][0]["authority"]["metadata_tags"]["values"] == {
        "title": "Canonical Edition",
        "artist": "Canonical Author",
        "album": "Canonical Edition",
        "album_artist": "Canonical Author",
    }
    assert report["books"][0]["authority"]["metadata_tags"]["field_map"] == {
        "title": "title",
        "artist": "artist",
        "album": "album",
        "album_artist": "album_artist",
    }
    assert [cap["kind"] for cap in report["books"][0]["capabilities"]] == [
        "audio.import",
        "metadata.tags",
        "publish.write",
    ]

    line0 = json.loads((roots["wizards"] / book1_log_rel).read_text(encoding="utf-8").strip())
    assert line0["status"] == "succeeded"
    assert line0["source"] == {"root": "inbox", "relative_path": "AuthorA/Book1"}
    assert line0["authority"]["metadata_tags"]["values"]["title"] == "Canonical Edition"

    dry_run_text = (roots["wizards"] / book1_dry_run_rel).read_text(encoding="utf-8")
    assert "title=Canonical Edition" in dry_run_text
    assert "artist=Canonical Author" in dry_run_text

    assert ignore_registry == {
        "schema_version": 1,
        "sources": [
            {"relative_path": "AuthorA/Book1", "root": "inbox"},
            {"relative_path": "AuthorA/Book2", "root": "inbox"},
        ],
    }

    finalize = state.get("computed", {}).get("finalize")
    assert finalize == {
        "job_id": job_id,
        "report_path": f"wizards:{report_rel}",
        "artifacts": {
            "report": f"wizards:{report_rel}",
            "processing_logs": {
                report_books["AuthorA/Book1"]: f"wizards:{book1_log_rel}",
                report_books["AuthorA/Book2"]: f"wizards:{book2_log_rel}",
            },
            "dry_run_texts": {
                report_books["AuthorA/Book1"]: f"wizards:{book1_dry_run_rel}",
                report_books["AuthorA/Book2"]: f"wizards:{book2_dry_run_rel}",
            },
        },
        "counts": {"books": 2, "capabilities": 6},
        "status": "succeeded",
    }
    assert state["status"] == "succeeded"
