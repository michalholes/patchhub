"""Issue 220: start_processing must reread job_requests.json for idempotency_key."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
RootName = import_module("plugins.file_io.service").RootName
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
read_json = import_module("plugins.import.storage").read_json


def _make_engine(tmp_path: Path) -> Any:
    roots = {
        "inbox": tmp_path / "inbox",
        "stage": tmp_path / "stage",
        "outbox": tmp_path / "outbox",
        "jobs": tmp_path / "jobs",
        "config": tmp_path / "config",
        "wizards": tmp_path / "wizards",
    }
    for p in roots.values():
        p.mkdir(parents=True, exist_ok=True)
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


def test_start_processing_uses_persisted_idempotency_key(tmp_path: Path, monkeypatch) -> None:
    engine = _make_engine(tmp_path)
    fs = engine.get_file_service()

    session_id = "s1"
    session_dir = f"import/sessions/{session_id}"

    state = {
        "session_id": session_id,
        "phase": 1,
        "status": "in_progress",
        "current_step_id": "final_summary_confirm",
        "root": "inbox",
        "relative_path": "src",
        "mode": "stage",
        "model_fingerprint": "m",
        "derived": {
            "discovery_fingerprint": "d",
            "effective_config_fingerprint": "c",
        },
        "conflicts": {
            "present": False,
            "items": [],
            "resolved": True,
            "policy": "ask",
        },
        "inputs": {},
        "vars": {"phase1": {"runtime": {"final_summary_confirm": {"confirm_start": True}}}},
        "answers": {},
        "computed": {},
        "selected_author_ids": [],
        "selected_book_ids": [],
        "effective_author_title": {},
        "created_at": "2026-02-20T00:00:00Z",
        "updated_at": "2026-02-20T00:00:00Z",
    }

    plan = {
        "selected_books": [
            {
                "book_id": "b1",
                "source_relative_path": "src/book",
                "proposed_target_relative_path": "dst/book",
            }
        ],
        "source": {"root": "inbox", "relative_path": "src"},
        "summary": {},
    }

    atomic_write_json(fs, RootName.WIZARDS, f"{session_dir}/state.json", state)
    atomic_write_json(fs, RootName.WIZARDS, f"{session_dir}/plan.json", plan)
    atomic_write_json(
        fs,
        RootName.WIZARDS,
        f"{session_dir}/effective_model.json",
        {"steps": [], "catalog": {}},
    )

    monkeypatch.setattr(engine, "_scan_conflicts", lambda *_args, **_kw: [])
    monkeypatch.setattr(engine, "_enter_phase_2", lambda *_args, **_kw: None)

    captured: dict[str, str] = {}

    def _capture(session_id_in: str, state_in: dict, idem_key: str) -> str:
        captured["idem_key"] = idem_key
        return "job123"

    monkeypatch.setattr(engine, "_get_or_create_job", _capture)
    diag_mod = import_module("plugins.import.engine_diagnostics_required")
    monkeypatch.setattr(diag_mod, "submit_process_job", lambda **_kw: None)

    eng_mod = import_module("plugins.import.engine")
    orig_atomic_write_text = eng_mod.atomic_write_text

    def _wrapped_atomic_write_text(fs_in, root_in, rel_path_in, text_in):
        orig_atomic_write_text(fs_in, root_in, rel_path_in, text_in)
        if rel_path_in.endswith("/job_requests.json"):
            obj = read_json(fs_in, root_in, rel_path_in)
            assert isinstance(obj, dict)
            obj["idempotency_key"] = "persisted_key"
            data = json.dumps(obj, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
            with fs_in.open_write(root_in, rel_path_in, overwrite=True, mkdir_parents=True) as f:
                f.write(data.encode("utf-8"))

    monkeypatch.setattr(eng_mod, "atomic_write_text", _wrapped_atomic_write_text)

    out = engine.start_processing(session_id, {"confirm": True})
    assert out.get("job_ids") == ["job123"]
    assert captured.get("idem_key") == "persisted_key"
