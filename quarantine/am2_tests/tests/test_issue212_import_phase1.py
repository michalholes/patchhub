from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
RootName = import_module("plugins.file_io.service").RootName
ensure_default_models = import_module("plugins.import.defaults").ensure_default_models
read_json = import_module("plugins.import.storage").read_json
DEFAULT_FLOW_CONFIG = import_module("plugins.import.defaults").DEFAULT_FLOW_CONFIG
build_router = import_module("plugins.import.ui_api").build_router

_HAS_FASTAPI = True
try:
    import fastapi  # noqa: F401
except Exception:
    _HAS_FASTAPI = False

try:
    import httpx  # noqa: F401

    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False


def _make_engine(tmp_path: Path):
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
    (d / "a.txt").write_text("x", encoding="utf-8")
    (d / "b.txt").write_text("y", encoding="utf-8")


def _submit_runtime_default(
    engine: object, session_id: str, step_id: str
) -> dict[str, object]:
    state = engine.get_state(session_id)
    runtime = state.get("vars", {}).get("phase1", {}).get("runtime", {})
    if step_id == "effective_author":
        author = runtime.get("effective_author_title", {}).get("author")
        return engine.submit_step(session_id, step_id, {"value": author})
    if step_id == "effective_title":
        title = runtime.get("effective_author_title", {}).get("title")
        return engine.submit_step(session_id, step_id, {"value": title})
    if step_id == "filename_policy_author":
        author = runtime.get("filename_policy", {}).get("author")
        return engine.submit_step(session_id, step_id, {"value": author})
    if step_id == "filename_policy_title":
        title = runtime.get("filename_policy", {}).get("title")
        return engine.submit_step(session_id, step_id, {"value": title})
    return engine.apply_action(session_id, "next")


def _advance_to(engine: object, session_id: str, target_step_id: str) -> None:
    for _ in range(100):
        state = engine.get_state(session_id)
        cur = str(state.get("current_step_id") or "")
        if cur == target_step_id:
            return
        state2 = _submit_runtime_default(engine, session_id, cur)
        cur2 = str(state2.get("current_step_id") or "")
        if cur2 == target_step_id:
            return
    raise AssertionError("failed to advance to step: " + target_step_id)


def test_session_state_min_fields_and_answers_are_canonical(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_source_dir(roots, "src")
    ensure_default_models(fs)

    state = engine.create_session("inbox", "src", mode="stage")
    assert "error" not in state

    for key in [
        "answers",
        "computed",
        "selected_author_ids",
        "selected_book_ids",
        "effective_author_title",
    ]:
        assert key in state

    assert state["vars"]["phase1"]["policy"]["clean_inbox"] == "ask"
    assert (
        state["vars"]["phase1"]["policy"]["root_audio_baseline"]["title"] == "Untitled"
    )

    session_id = str(state["session_id"])

    # select_authors updates answers and selected_author_ids.
    state2 = engine.submit_step(session_id, "select_authors", {"selection": "1"})
    assert "error" not in state2

    ans = state2.get("answers")
    assert isinstance(ans, dict)
    assert "select_authors" in ans

    sel = state2.get("selected_author_ids")
    assert isinstance(sel, list)
    assert len(sel) == 1


def test_compute_plan_populates_state_computed_plan_summary(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_source_dir(roots, "src")
    ensure_default_models(fs)

    state = engine.create_session("inbox", "src", mode="stage")
    session_id = str(state["session_id"])

    state = engine.submit_step(session_id, "select_authors", {"selection": "1"})
    assert "error" not in state
    if str(state.get("current_step_id") or "") == "select_books":
        state = engine.submit_step(session_id, "select_books", {"selection": "1"})
        assert "error" not in state
    if str(state.get("current_step_id") or "") == "effective_author":
        state = engine.submit_step(session_id, "effective_author", {"value": "src"})
        assert "error" not in state
    if str(state.get("current_step_id") or "") == "effective_title":
        state = engine.submit_step(session_id, "effective_title", {"value": "src"})
        assert "error" not in state
    _advance_to(engine, session_id, "covers_policy_mode")

    plan = engine.compute_plan(session_id)
    assert isinstance(plan, dict)

    state2 = engine.get_state(session_id)
    computed = state2.get("computed")
    assert isinstance(computed, dict)
    ps = computed.get("plan_summary")
    assert isinstance(ps, dict)
    assert ps["files"] >= 2
    assert ps["dirs"] >= 0
    assert ps["bundles"] >= 0

    sp = ps.get("selected_policies")
    assert isinstance(sp, dict)
    assert sp.get("filename_policy") == {"author": "src", "title": "src"}
    assert state2["vars"]["phase1"]["runtime"]["filename_policy"]["mode"] == "keep"


@pytest.mark.skipif(
    (not _HAS_FASTAPI) or (not _HAS_HTTPX), reason="fastapi+httpx required"
)
def test_config_reset_uses_builtin_defaults(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    engine, _roots = _make_engine(tmp_path)
    fs = engine.get_file_service()
    ensure_default_models(fs)

    # Make ACTIVE non-default so the test can prove that /config/reset only touches DRAFT.
    atomic_write_json = import_module("plugins.import.storage").atomic_write_json
    active_marker = {"version": 1, "steps": {}, "defaults": {"marker": 9}}
    atomic_write_json(
        fs, RootName.WIZARDS, "import/config/flow_config.json", active_marker
    )

    app = FastAPI()
    app.include_router(build_router(engine=engine))
    client = TestClient(app)

    resp = client.post("/import/ui/config/reset")
    assert resp.status_code == 200

    data = resp.json()["config"]
    assert isinstance(data, dict)
    assert data == engine._normalize_flow_config(DEFAULT_FLOW_CONFIG)

    # ACTIVE must remain unchanged until /config/activate.
    stored_active = read_json(fs, RootName.WIZARDS, "import/config/flow_config.json")
    assert stored_active == active_marker

    client.post("/import/ui/config/activate")
    stored_after = read_json(fs, RootName.WIZARDS, "import/config/flow_config.json")
    assert stored_after == data


def test_cli_renderer_finalize_calls_start_processing_only() -> None:
    mod = import_module("plugins.import.cli_renderer")

    class DummyEngine:
        def __init__(self) -> None:
            self.called = False

        def start_processing(self, session_id: str, body: dict[str, object]):
            self.called = True
            assert session_id == "sid"
            assert body == {"confirm": True}
            return {"job_ids": ["job1"], "batch_size": 1}

        def finalize(self, session_id: str):  # pragma: no cover
            raise AssertionError("finalize must not be called")

    eng = DummyEngine()

    out: list[str] = []

    def _print(s: str) -> None:
        out.append(s)

    rc = mod._finalize(eng, "sid", print_fn=_print)
    assert rc == 0
    assert eng.called is True
    assert any("job_ids" in line for line in out)
    assert any("batch_size" in line for line in out)
