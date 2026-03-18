"""Import plugin: session snapshot artifacts are immutable (spec 10.9).

The effective_model.json snapshot must never be rewritten after session creation.
model_fingerprint is allowed to track the runtime-effective model fingerprint.
"""

from __future__ import annotations

import copy
import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

fingerprint_json = import_module("plugins.import.fingerprints").fingerprint_json

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
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver), roots


def _write_inbox_source_dir(roots: dict[str, Path], rel_dir: str) -> None:
    d = roots["inbox"] / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "file.txt").write_text("x", encoding="utf-8")


def _mutate_effective_model(effective_model: dict) -> dict:
    em = copy.deepcopy(effective_model)
    em["flow_id"] = str(em.get("flow_id") or "") + "_snapshot"
    return em


def test_fingerprint_matches_persisted_effective_model(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "src")

    state = engine.create_session("inbox", "src", mode="stage")
    session_id = str(state.get("session_id") or "")
    assert session_id

    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    em = json.loads((session_dir / "effective_model.json").read_text(encoding="utf-8"))
    st = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))

    assert fingerprint_json(em) == st.get("model_fingerprint")


def test_resume_reinjection_updates_fingerprint_only_when_model_changed(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_inbox_source_dir(roots, "src2")

    state = engine.create_session("inbox", "src2", mode="stage")
    session_id = str(state.get("session_id") or "")
    assert session_id

    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    em_path = session_dir / "effective_model.json"
    st_path = session_dir / "state.json"

    em_full = json.loads(em_path.read_text(encoding="utf-8"))
    em_stripped = _mutate_effective_model(em_full)
    assert fingerprint_json(em_stripped) != fingerprint_json(em_full)

    # Simulate an older persisted model/state fingerprint pair.
    em_path.write_text(
        json.dumps(em_stripped, ensure_ascii=True, sort_keys=True), encoding="utf-8"
    )
    st_old = json.loads(st_path.read_text(encoding="utf-8"))
    st_old["model_fingerprint"] = fingerprint_json(em_stripped)
    st_path.write_text(
        json.dumps(st_old, ensure_ascii=True, sort_keys=True), encoding="utf-8"
    )

    # create_session sees an existing session and runs the upgrader.
    resumed = engine.create_session("inbox", "src2", mode="stage")
    assert resumed.get("session_id") == session_id

    em_after = json.loads(em_path.read_text(encoding="utf-8"))
    st_after = json.loads(st_path.read_text(encoding="utf-8"))

    # Snapshot stays immutable (legacy stripped model remains on disk).
    assert fingerprint_json(em_after) == fingerprint_json(em_stripped)

    # State continues to track the immutable persisted snapshot fingerprint.
    assert st_after.get("model_fingerprint") == fingerprint_json(em_stripped)
    assert st_after.get("model_fingerprint") == st_old.get("model_fingerprint")
