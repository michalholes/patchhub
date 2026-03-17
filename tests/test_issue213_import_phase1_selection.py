from __future__ import annotations

from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

ImportWizardEngine = import_module("plugins.import.engine").ImportWizardEngine
RootName = import_module("plugins.file_io.service").RootName
ensure_default_models = import_module("plugins.import.defaults").ensure_default_models
read_json = import_module("plugins.import.storage").read_json


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


def _write_inbox_tree(roots: dict[str, Path]) -> None:
    # Author A / Book 1
    d = roots["inbox"] / "A" / "Book1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.txt").write_text("x", encoding="utf-8")

    # Author A / Book 2
    d = roots["inbox"] / "A" / "Book2"
    d.mkdir(parents=True, exist_ok=True)
    (d / "b.txt").write_text("y", encoding="utf-8")

    # Author B / Book 3
    d = roots["inbox"] / "B" / "Book3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "c.txt").write_text("z", encoding="utf-8")

    # Unicode author/title (diacritics), encoded as escapes to keep repo ASCII-only.
    author = "Meyr\u00ednk, Gust\u00e1v"
    book = "Obrazy vep\u00edsan\u00e9 do vzduchu"
    d = roots["inbox"] / author / book
    d.mkdir(parents=True, exist_ok=True)
    (d / "u.txt").write_text("u", encoding="utf-8")


def test_effective_model_contains_selection_items(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_tree(roots)
    ensure_default_models(fs)

    state = engine.create_session("inbox", "", mode="stage")
    assert "error" not in state

    phase1 = state.get("vars", {}).get("phase1", {})
    authors = phase1.get("select_authors", {})
    books = phase1.get("select_books", {})
    assert authors.get("ordered_ids")
    assert books.get("ordered_ids")

    state2 = engine.submit_step(
        str(state["session_id"]), "select_authors", {"selection": "all"}
    )
    assert "error" not in state2
    state2 = engine.submit_step(
        str(state["session_id"]), "select_books", {"selection": "all"}
    )
    assert "error" not in state2
    selected = state2.get("selected_book_ids") or []
    assert isinstance(selected, list)
    assert selected
    assert all(str(item_id).startswith("book:") for item_id in selected)


def test_out_of_range_selection_is_validation_error(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_tree(roots)
    ensure_default_models(fs)

    state = engine.create_session("inbox", "", mode="stage")
    session_id = str(state["session_id"])

    state = engine.submit_step(session_id, "select_authors", {"selection": "all"})
    assert "error" not in state
    res = engine.submit_step(session_id, "select_books", {"selection": "999"})
    err = res.get("error") if isinstance(res, dict) else None
    assert isinstance(err, dict)
    assert err.get("code") == "VALIDATION_ERROR"


def test_cli_renderer_has_no_step_id_branching() -> None:
    p = Path(__file__).resolve().parents[1] / "plugins" / "import" / "cli_renderer.py"
    txt = p.read_text(encoding="utf-8")
    assert "if step_id ==" not in txt


def test_cli_launcher_uses_raw_path_prompt_without_directory_listing(
    tmp_path: Path,
) -> None:
    facade = import_module("plugins.import.cli_launcher_facade")

    class _Cfg:
        launcher_mode = "interactive"
        default_root = "inbox"
        default_path = ""
        confirm_defaults = True
        nav_ui = "prompt"

    prompts: list[str] = []
    printed: list[str] = []
    answers = iter(["", "A/Book1"])

    ok, root, rel_path, err = facade.resolve_launcher_inputs(
        engine=object(),
        cfg=_Cfg(),
        input_fn=lambda prompt: prompts.append(prompt) or next(answers),
        print_fn=printed.append,
    )

    assert ok is True
    assert root == "inbox"
    assert rel_path == "A/Book1"
    assert err == ""
    assert prompts == [
        "Enter root number (Enter=default): ",
        "Enter path (relative) (Enter=default): ",
    ]
    joined = "\n".join(printed)
    assert "  0. (root)" not in joined
    assert "Select path (relative):" not in joined
    assert "Path is relative to the selected root." in joined


def test_author_scoped_path_skips_duplicate_author_prompt(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_tree(roots)
    ensure_default_models(fs)

    state = engine.create_session("inbox", "A", mode="stage")
    assert "error" not in state
    assert state.get("current_step_id") == "select_books"

    phase1 = state.get("vars", {}).get("phase1", {})
    authors = phase1.get("select_authors", {})
    books = phase1.get("select_books", {})
    assert authors.get("autofill_if") is True
    assert books.get("autofill_if") is False
    assert books.get("selected_source_relative_paths") == ["Book1", "Book2"]

    step = engine.get_step_definition(str(state["session_id"]), "select_books")
    assert [item["display_label"] for item in step["ui"]["items"]] == [
        "A / Book1",
        "A / Book2",
    ]


def test_book_scoped_path_skips_duplicate_author_and_book_prompts(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_tree(roots)
    ensure_default_models(fs)

    state = engine.create_session("inbox", "A/Book1", mode="stage")
    assert "error" not in state
    assert state.get("current_step_id") == "effective_author"

    phase1 = state.get("vars", {}).get("phase1", {})
    authors = phase1.get("select_authors", {})
    books = phase1.get("select_books", {})
    assert authors.get("autofill_if") is True
    assert books.get("autofill_if") is True
    assert books.get("selected_source_relative_paths") == [""]


def test_unicode_author_scoped_path_keeps_canonical_phase1_labels(
    tmp_path: Path,
) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_tree(roots)
    ensure_default_models(fs)

    author = "Meyr\u00ednk, Gust\u00e1v"
    title = "Obrazy vep\u00edsan\u00e9 do vzduchu"
    state = engine.create_session("inbox", author, mode="stage")
    assert "error" not in state
    assert state.get("current_step_id") == "effective_author"

    phase1 = state.get("vars", {}).get("phase1", {})
    books = phase1.get("select_books", {})
    assert books.get("selected_source_relative_paths") == [title]
    runtime = phase1.get("runtime", {}).get("effective_author_title", {})
    assert runtime == {"author": author, "title": title}


def test_root_scoped_author_filter_keeps_local_book_ordinals(tmp_path: Path) -> None:
    engine, roots = _make_engine(tmp_path)
    fs = engine.get_file_service()

    _write_inbox_tree(roots)
    ensure_default_models(fs)

    state = engine.create_session("inbox", "", mode="stage")
    session_id = str(state["session_id"])
    state = engine.submit_step(session_id, "select_authors", {"selection": "1"})
    assert "error" not in state
    assert state.get("current_step_id") == "select_books"

    step = engine.get_step_definition(session_id, "select_books")
    assert [item["display_label"] for item in step["ui"]["items"]] == [
        "A / Book1",
        "A / Book2",
    ]

    phase1 = state.get("vars", {}).get("phase1", {})
    books = phase1.get("select_books", {})
    assert books.get("selection_expr") == "all"

    state = engine.submit_step(session_id, "select_books", {"selection": "2"})
    assert "error" not in state

    phase1 = state.get("vars", {}).get("phase1", {})
    books = phase1.get("select_books", {})
    selected_ids = books.get("selected_ids") or []
    assert books.get("selection_expr") == "2"
    assert books.get("selected_source_relative_paths") == ["A/Book2"]
    assert isinstance(selected_ids, list) and len(selected_ids) == 1
    assert state.get("selected_book_ids") == selected_ids

    plan = engine.compute_plan(session_id)
    assert plan.get("summary", {}).get("selected_books") == 1
    assert [
        item.get("source_relative_path") for item in plan.get("selected_books", [])
    ] == ["A/Book2"]

    out = engine.submit_step(session_id, "select_books", {"selection": "3"})
    err = out.get("error") if isinstance(out, dict) else None
    assert isinstance(err, dict)
    assert err.get("code") == "VALIDATION_ERROR"
