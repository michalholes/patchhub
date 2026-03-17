from __future__ import annotations

import gc
import json
import warnings
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
atomic_write_json = import_module("plugins.import.storage").atomic_write_json
RootName = import_module("plugins.file_io.service.types").RootName
WIZARD_DEFINITION_REL_PATH = import_module(
    "plugins.import.wizard_definition_model"
).WIZARD_DEFINITION_REL_PATH
build_default_wizard_definition_v3 = import_module(
    "plugins.import.dsl.default_wizard_v3"
).build_default_wizard_definition_v3


def _make_engine(tmp_path: Path) -> tuple[ImportWizardEngine, dict[str, Path]]:
    roots = {
        name: tmp_path / name
        for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
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
    engine = ImportWizardEngine(resolver=resolver)
    atomic_write_json(
        engine.get_file_service(),
        RootName.WIZARDS,
        WIZARD_DEFINITION_REL_PATH,
        build_default_wizard_definition_v3(),
    )
    return engine, roots


def _write_book(
    root: Path, author: str, book: str, filename: str = "track01.mp3"
) -> None:
    book_dir = root / author / book
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / filename).write_text("x", encoding="utf-8")


def test_create_session_autofills_single_author_and_single_book(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_book(roots["inbox"], "Author", "Book")

    state = engine.create_session("inbox", "", mode="stage")

    assert state["current_step_id"] == "effective_author"
    assert state["answers"]["select_authors"]["selection_expr"] == "1"
    assert state["answers"]["select_books"]["selection_expr"] == "1"
    assert state["vars"]["phase1"]["metadata"]["values"] == {
        "title": "Book",
        "artist": "Author",
        "album": "Book",
        "album_artist": "Author",
    }
    assert state["vars"]["phase1"]["cover"]["mode"] == "embedded"
    assert state["vars"]["phase1"]["runtime"]["effective_author_title"] == {
        "author": "Author",
        "title": "Book",
    }
    assert state["vars"]["phase1"]["policy"]["publish_policy"] == {
        "target_root": "stage"
    }


def test_select_authors_refreshes_filtered_book_defaults_for_two_pass_flow(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_book(roots["inbox"], "A", "Book1")
    _write_book(roots["inbox"], "A", "Book2")
    _write_book(roots["inbox"], "B", "Book3")

    state = engine.create_session("inbox", "", mode="stage")
    session_id = str(state["session_id"])
    state = engine.submit_step(session_id, "select_authors", {"selection": "1"})

    assert state["current_step_id"] == "select_books"
    assert state["vars"]["phase1"]["select_books"]["selection_expr"] == "all"
    assert state["vars"]["phase1"]["select_books"][
        "selected_source_relative_paths"
    ] == [
        "A/Book1",
        "A/Book2",
    ]


def test_load_state_repairs_missing_phase1_projection_on_resume(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_book(roots["inbox"], "Author", "Book")

    state = engine.create_session("inbox", "", mode="stage")
    session_id = str(state["session_id"])
    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    stored = json.loads(state_path.read_text(encoding="utf-8"))
    stored["vars"] = {}
    state_path.write_text(json.dumps(stored), encoding="utf-8")

    repaired = engine.get_state(session_id)

    assert repaired["vars"]["phase1"]["select_authors"]["selection_expr"] == "1"
    assert repaired["vars"]["phase1"]["select_books"]["selection_expr"] == "1"


def test_create_session_uses_metadata_validation_and_explicit_cover_choice(
    monkeypatch, tmp_path: Path
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_book(roots["inbox"], "A", "Book")

    phase1_cover = import_module("plugins.import.phase1_cover_flow")
    phase1_metadata = import_module("plugins.import.phase1_metadata_flow")

    def _fake_validate(author: str, title: str) -> tuple[dict[str, object], str, str]:
        assert author == "A"
        assert title == "Book"
        return (
            {
                "provider": "metadata_openlibrary",
                "author": {"valid": False, "canonical": None, "suggestion": "Author A"},
                "book": {
                    "valid": False,
                    "canonical": None,
                    "suggestion": {"author": "Author A", "title": "Canonical Book"},
                },
            },
            "Author A",
            "Canonical Book",
        )

    def _fake_discover(
        self,
        directory: Path,
        *,
        audio_file: Path | None = None,
        group_root: str | None = None,
    ):
        assert directory == roots["inbox"] / "A" / "Book"
        assert audio_file == roots["inbox"] / "A" / "Book" / "track01.mp3"
        assert group_root == "inbox"
        return [
            {
                "kind": "file",
                "candidate_id": "file:canonical-cover.png",
                "apply_mode": "copy",
                "path": str(directory / "canonical-cover.png"),
                "mime_type": "image/png",
                "cache_key": "file:canonical-cover.png",
                "root_name": group_root or "",
            }
        ]

    monkeypatch.setattr(phase1_metadata, "_validated_author_title", _fake_validate)
    monkeypatch.setattr(
        phase1_cover.CoverHandlerPlugin,
        "discover_cover_candidates",
        _fake_discover,
    )

    state = engine.create_session("inbox", "", mode="stage")

    assert (
        state["vars"]["phase1"]["metadata"]["validation"]["provider"]
        == "metadata_openlibrary"
    )
    assert state["vars"]["phase1"]["runtime"]["effective_author_title"] == {
        "author": "Author A",
        "title": "Canonical Book",
    }
    assert state["vars"]["phase1"]["cover"]["choice"] == {
        "kind": "candidate",
        "candidate_id": "file:canonical-cover.png",
        "source_relative_path": "A/Book",
    }
    assert state["vars"]["phase1"]["runtime"]["covers_policy"]["candidates"][0][
        "candidate_id"
    ] == ("file:canonical-cover.png")
    assert state["vars"]["phase1"]["runtime"]["covers_policy"]["candidates"][0][
        "path"
    ] == ("A/Book/canonical-cover.png")


def test_default_v3_phase1_runtime_step_uses_flow_visible_runtime_projection() -> None:
    definition = build_default_wizard_definition_v3()
    phase1_node = next(
        node
        for node in definition["nodes"]
        if node["step_id"] == "phase1_runtime_defaults"
    )
    op = phase1_node["op"]

    assert op["primitive_id"] == "import.phase1_runtime"
    assert op["inputs"] == {}
    assert op["writes"] == [
        {
            "to_path": "$.state.vars.phase1.runtime",
            "value": {"expr": "$.op.outputs.snapshot"},
        }
    ]


async def test_create_session_under_running_loop_awaits_metadata_validation_without_warning(
    monkeypatch, tmp_path: Path
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_book(roots["inbox"], "A", "Book")

    phase1_metadata = import_module("plugins.import.phase1_metadata_flow")
    metadata_plugin = import_module("plugins.metadata_openlibrary.plugin")
    phase1_metadata._openlibrary_validate.cache_clear()

    async def _validate_author(self, name: str) -> dict[str, object]:
        assert name == "A"
        return {"valid": False, "canonical": None, "suggestion": "Author A"}

    async def _validate_book(self, author: str, title: str) -> dict[str, object]:
        assert author == "Author A"
        assert title == "Book"
        return {
            "valid": False,
            "canonical": None,
            "suggestion": {"author": "Author A", "title": "Canonical Book"},
        }

    monkeypatch.setattr(
        metadata_plugin.OpenLibraryPlugin, "validate_author", _validate_author
    )
    monkeypatch.setattr(
        metadata_plugin.OpenLibraryPlugin, "validate_book", _validate_book
    )

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        state = engine.create_session("inbox", "", mode="stage")
        gc.collect()

    assert not any("was never awaited" in str(item.message) for item in seen)
    assert state["vars"]["phase1"]["metadata"]["validation"] == {
        "provider": "metadata_openlibrary",
        "author": {"valid": False, "canonical": None, "suggestion": "Author A"},
        "book": {
            "valid": False,
            "canonical": None,
            "suggestion": {"author": "Author A", "title": "Canonical Book"},
        },
    }
    assert state["vars"]["phase1"]["runtime"]["effective_author_title"] == {
        "author": "Author A",
        "title": "Canonical Book",
    }


async def test_resume_repair_under_running_loop_rebuilds_phase1_without_warning(
    monkeypatch, tmp_path: Path
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_book(roots["inbox"], "A", "Book")

    phase1_metadata = import_module("plugins.import.phase1_metadata_flow")
    metadata_plugin = import_module("plugins.metadata_openlibrary.plugin")
    phase1_metadata._openlibrary_validate.cache_clear()

    async def _validate_author(self, name: str) -> dict[str, object]:
        assert name == "A"
        return {"valid": False, "canonical": None, "suggestion": "Author A"}

    async def _validate_book(self, author: str, title: str) -> dict[str, object]:
        assert author == "Author A"
        assert title == "Book"
        return {
            "valid": False,
            "canonical": None,
            "suggestion": {"author": "Author A", "title": "Canonical Book"},
        }

    monkeypatch.setattr(
        metadata_plugin.OpenLibraryPlugin, "validate_author", _validate_author
    )
    monkeypatch.setattr(
        metadata_plugin.OpenLibraryPlugin, "validate_book", _validate_book
    )

    state = engine.create_session("inbox", "", mode="stage")
    session_id = str(state["session_id"])
    state_path = roots["wizards"] / "import" / "sessions" / session_id / "state.json"
    stored = json.loads(state_path.read_text(encoding="utf-8"))
    stored["vars"] = {}
    state_path.write_text(json.dumps(stored), encoding="utf-8")
    phase1_metadata._openlibrary_validate.cache_clear()

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        repaired = engine.create_session("inbox", "", mode="stage")
        gc.collect()

    assert not any("was never awaited" in str(item.message) for item in seen)
    assert repaired["vars"]["phase1"]["runtime"]["effective_author_title"] == {
        "author": "Author A",
        "title": "Canonical Book",
    }
    assert repaired["vars"]["phase1"]["metadata"]["validation"]["provider"] == (
        "metadata_openlibrary"
    )


async def test_create_session_under_running_loop_keeps_fallback_on_validation_failure(
    monkeypatch, tmp_path: Path
) -> None:
    engine, roots = _make_engine(tmp_path)
    _write_book(roots["inbox"], "Author", "Book")

    phase1_metadata = import_module("plugins.import.phase1_metadata_flow")
    metadata_plugin = import_module("plugins.metadata_openlibrary.plugin")
    phase1_metadata._openlibrary_validate.cache_clear()

    async def _fail_author(self, name: str) -> dict[str, object]:
        del self, name
        raise RuntimeError("boom")

    async def _fail_book(self, author: str, title: str) -> dict[str, object]:
        del self, author, title
        raise RuntimeError("boom")

    monkeypatch.setattr(
        metadata_plugin.OpenLibraryPlugin, "validate_author", _fail_author
    )
    monkeypatch.setattr(metadata_plugin.OpenLibraryPlugin, "validate_book", _fail_book)

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        state = engine.create_session("inbox", "", mode="stage")
        gc.collect()

    assert not any("was never awaited" in str(item.message) for item in seen)
    assert state["vars"]["phase1"]["metadata"]["validation"] == {
        "provider": "metadata_openlibrary",
        "author": {"valid": False, "canonical": None, "suggestion": None},
        "book": {"valid": False, "canonical": None, "suggestion": None},
    }
    assert state["vars"]["phase1"]["runtime"]["effective_author_title"] == {
        "author": "Author",
        "title": "Book",
    }
