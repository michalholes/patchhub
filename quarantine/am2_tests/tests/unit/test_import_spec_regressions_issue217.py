"""Import wizard: spec regression tests (issue 217).

These tests enforce import wizard invariants that prevent "no-op wizard" regressions:
- selection grammar and stable ordering
- plan derived from selection
- conflicts derived from plan
- job_requests derived from plan with correct batch_size and idempotency
- renderer neutrality (no step_id branching)
"""

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
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return ImportWizardEngine(resolver=resolver), roots


def _write_inbox_books(roots: dict[str, Path], rel_dir: str) -> None:
    base = roots["inbox"] / rel_dir if rel_dir else roots["inbox"]
    (base / "AuthorA" / "Book1").mkdir(parents=True, exist_ok=True)
    (base / "AuthorA" / "Book2").mkdir(parents=True, exist_ok=True)
    (base / "AuthorA" / "Book1" / "file1.txt").write_text("x", encoding="utf-8")
    (base / "AuthorA" / "Book2" / "file2.txt").write_text("x", encoding="utf-8")


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


def _mutate_state_for_finalize(roots: dict[str, Path], session_id: str, *, policy: str) -> None:
    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("answers", {})["final_summary_confirm"] = {"confirm_start": True}
    state.setdefault("conflicts", {})["policy"] = policy
    state["status"] = "in_progress"
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_selection_expr_grammar_and_stable_ordering(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    rel = ""
    _write_inbox_books(roots, rel)

    state = engine.create_session(
        "inbox",
        rel,
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id

    assert state.get("current_step_id") == "select_books"

    item_ids = state.get("vars", {}).get("phase1", {}).get("select_books", {}).get("ordered_ids")
    assert isinstance(item_ids, list)
    assert len(item_ids) == 2

    # Whitespace + duplicates + reverse order in expression must not affect output order.
    state = engine.submit_step(session_id, "select_books", {"selection": " 2, 1, 1 "})
    assert state.get("current_step_id") == "effective_author"
    assert state.get("selected_book_ids") == item_ids


def test_selection_expr_out_of_range_returns_validation_error(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    rel = ""
    _write_inbox_books(roots, rel)

    state = engine.create_session(
        "inbox",
        rel,
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id

    assert state.get("current_step_id") == "select_books"

    out = engine.submit_step(session_id, "select_books", {"selection": "3"})
    assert out.get("error", {}).get("code") == "VALIDATION_ERROR"


def test_plan_is_derived_from_selected_books(tmp_path: Path) -> None:
    def _select(expr: str) -> tuple[str, dict[str, Any]]:
        base = tmp_path / f"case_{expr.replace(',', '_').replace(' ', '')}"
        base.mkdir(parents=True, exist_ok=True)
        engine, roots = _make_engine(base)
        rel = ""
        _write_inbox_books(roots, rel)

        st = engine.create_session(
            "inbox",
            rel,
            mode="stage",
            flow_overrides=_disable_optional_steps(),
        )
        sid = str(st.get("session_id") or "")
        assert sid
        assert st.get("current_step_id") == "select_books"

        st2 = engine.submit_step(sid, "select_books", {"selection": expr})
        assert "error" not in st2
        plan = engine.compute_plan(sid)
        assert isinstance(plan, dict)
        return sid, plan

    _sid_all, plan_all = _select("all")
    _sid_one, plan_one = _select("1")

    assert plan_all.get("summary", {}).get("selected_books") == 2
    assert plan_one.get("summary", {}).get("selected_books") == 1

    b_all = [b.get("book_id") for b in plan_all.get("selected_books", [])]
    b_one = [b.get("book_id") for b in plan_one.get("selected_books", [])]
    assert len(b_all) == 2
    assert len(b_one) == 1
    assert b_one[0] in set(b_all)


def test_conflicts_are_derived_from_plan_targets(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    rel = ""
    _write_inbox_books(roots, rel)

    state = engine.create_session(
        "inbox",
        rel,
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id
    assert state.get("current_step_id") == "select_books"
    _ = engine.submit_step(session_id, "select_books", {"selection": "1"})

    plan = engine.compute_plan(session_id)
    target_rel = plan.get("selected_books", [])[0].get("proposed_target_relative_path")
    assert isinstance(target_rel, str) and target_rel
    (roots["stage"] / target_rel).mkdir(parents=True, exist_ok=True)

    _mutate_state_for_finalize(roots, session_id, policy="ask")
    out = engine.start_processing(session_id, {"confirm": True})
    assert out.get("error", {}).get("code") == "CONFLICTS_UNRESOLVED"

    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    conflicts = json.loads((session_dir / "conflicts.json").read_text(encoding="utf-8"))
    assert conflicts and conflicts[0].get("target_relative_path") == target_rel
    assert conflicts[0].get("source_book_id") == plan.get("selected_books", [])[0].get("book_id")


def test_job_requests_derived_from_plan_batch_size_and_idempotency(
    monkeypatch, tmp_path: Path
) -> None:
    engine, roots = _make_engine(tmp_path)
    rel = ""
    _write_inbox_books(roots, rel)

    state = engine.create_session(
        "inbox",
        rel,
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id
    assert state.get("current_step_id") == "select_books"
    _ = engine.submit_step(session_id, "select_books", {"selection": "all"})
    plan = engine.compute_plan(session_id)

    from audiomason.core.jobs import api as jobs_api

    def _create_job(self, job_type, *, meta):
        return _Job(job_id="job-217")

    monkeypatch.setattr(jobs_api.JobService, "create_job", _create_job)

    submit_calls: list[tuple[str, int]] = []

    def _submit_process_job(*, engine: object, job_id: str, verbosity: int = 1) -> None:
        assert engine is not None
        submit_calls.append((job_id, verbosity))

    diag_mod = import_module("plugins.import.engine_diagnostics_required")
    monkeypatch.setattr(diag_mod, "submit_process_job", _submit_process_job)

    _mutate_state_for_finalize(roots, session_id, policy="auto")
    out1 = engine.start_processing(session_id, {"confirm": True})
    out2 = engine.start_processing(session_id, {"confirm": True})

    assert out1.get("batch_size") == 2
    assert out2.get("batch_size") == 2
    assert out1.get("job_ids") == ["job-217"]
    assert out2.get("job_ids") == ["job-217"]
    assert submit_calls == [("job-217", 1)]

    session_dir = roots["wizards"] / "import" / "sessions" / session_id
    job_doc = json.loads((session_dir / "job_requests.json").read_text(encoding="utf-8"))
    assert isinstance(job_doc.get("idempotency_key"), str) and job_doc.get("idempotency_key")
    actions = job_doc.get("actions")
    assert isinstance(actions, list) and len(actions) == 2

    planned_ids = [b.get("book_id") for b in plan.get("selected_books", [])]
    action_ids = [a.get("book_id") for a in actions if isinstance(a, dict)]
    assert action_ids == planned_ids


def test_final_summary_confirm_enters_phase2_boundary_without_processing_stop(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(tmp_path)
    rel = ""
    _write_inbox_books(roots, rel)

    state = engine.create_session(
        "inbox",
        rel,
        mode="stage",
        flow_overrides=_disable_optional_steps(),
    )
    session_id = str(state.get("session_id") or "")
    assert session_id
    assert state.get("current_step_id") == "select_books"

    state = engine.submit_step(session_id, "select_books", {"selection": "1"})
    assert "error" not in state

    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    state_json = json.loads(state_path.read_text(encoding="utf-8"))
    state_json["phase"] = 1
    state_json["status"] = "in_progress"
    state_json["current_step_id"] = "final_summary_confirm"
    state_json.setdefault("cursor", {})["step_id"] = "final_summary_confirm"
    state_json.setdefault("answers", {})["conflict_policy"] = {"mode": "auto"}
    runtime = state_json.setdefault("vars", {}).setdefault("phase1", {}).setdefault("runtime", {})
    runtime.setdefault("resolve_conflicts_batch", {})["has_conflicts"] = False
    state_path.write_text(json.dumps(state_json), encoding="utf-8")

    out = engine.submit_step(session_id, "final_summary_confirm", {"confirmed": True})

    assert out.get("phase") == 2
    assert out.get("status") == "in_progress"
    assert out.get("current_step_id") == "processing"
    assert out.get("trace")[-1]["step_id"] == "final_summary_confirm"
    assert "processing" not in [entry["step_id"] for entry in out.get("trace", [])]


def test_cli_renderer_has_no_step_id_branching() -> None:
    p = Path(__file__).parent.parent.parent / "plugins" / "import" / "cli_renderer.py"
    text = p.read_text(encoding="utf-8")

    # Renderer must not special-case specific step ids like "processing".
    forbidden = [
        'cur == "processing"',
        "cur == 'processing'",
        'current_step_id" or "") == "processing"',
        'current_step_id" or "") == \'processing\'',
    ]
    assert not any(tok in text for tok in forbidden)
