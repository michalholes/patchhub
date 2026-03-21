"""Import plugin: conflict re-check tests."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

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


def _mutate_state_for_finalize(roots: dict[str, Path], session_id: str, *, policy: str) -> None:
    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("inputs", {})["final_summary_confirm"] = {"confirm_start": True}
    state.setdefault("conflicts", {})["policy"] = policy
    state["status"] = "in_progress"
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_conflict_recheck_policy_ask_blocks_job(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    rel = "book3"
    _write_inbox_source_dir(roots, rel)

    state = engine.create_session("inbox", rel, mode="stage")
    session_id = str(state.get("session_id") or "")
    assert session_id

    # Preview conflicts fingerprint during plan computation.
    _ = engine.compute_plan(session_id)
    _mutate_state_for_finalize(roots, session_id, policy="ask")

    # Introduce a conflict after preview.
    conflict_dir = roots["stage"] / rel
    conflict_dir.mkdir(parents=True, exist_ok=True)

    out = engine.start_processing(session_id, {"confirm": True})
    assert out.get("error", {}).get("code") == "CONFLICTS_UNRESOLVED"

    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    assert not (session_dir / "job_requests.json").exists()
    assert not (session_dir / "idempotency.json").exists()


def test_conflict_recheck_non_ask_detects_changed_since_preview(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    rel = "book4"
    _write_inbox_source_dir(roots, rel)

    state = engine.create_session("inbox", rel, mode="stage")
    session_id = str(state.get("session_id") or "")
    assert session_id

    _ = engine.compute_plan(session_id)
    _mutate_state_for_finalize(roots, session_id, policy="auto")

    conflict_dir = roots["stage"] / rel
    conflict_dir.mkdir(parents=True, exist_ok=True)

    out = engine.start_processing(session_id, {"confirm": True})
    assert out.get("error", {}).get("code") == "INVARIANT_VIOLATION"

    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    assert not (session_dir / "job_requests.json").exists()
    assert not (session_dir / "idempotency.json").exists()
