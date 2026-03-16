from __future__ import annotations

from pathlib import Path


def _import_gate():
    from am_patch.gates import check_js_gate

    return check_js_gate


def _import_run_gate():
    from am_patch.gates import run_js_syntax_gate

    return run_js_syntax_gate


def test_js_gate_not_triggered_when_no_js_touched() -> None:
    check_js_gate = _import_gate()
    triggered, js_paths = check_js_gate(
        ["src/a.py", "docs/specification.md"],
        extensions=[".js"],
    )
    assert triggered is False
    assert js_paths == []


def test_js_gate_triggers_and_sorts_paths() -> None:
    check_js_gate = _import_gate()
    triggered, js_paths = check_js_gate(
        ["b.js", "a.js", "src/x.py", "plugins/p.mjs"],
        extensions=[".js", ".mjs"],
    )
    assert triggered is True
    assert js_paths == ["a.js", "b.js", "plugins/p.mjs"]


def test_js_gate_respects_extensions_filter() -> None:
    check_js_gate = _import_gate()
    triggered, js_paths = check_js_gate(["a.mjs", "b.js"], extensions=[".js"])
    assert triggered is True
    assert js_paths == ["b.js"]


def test_js_gate_handles_extension_without_dot() -> None:
    check_js_gate = _import_gate()
    triggered, js_paths = check_js_gate(["a.JS", "b.txt"], extensions=["js"])
    assert triggered is True
    assert js_paths == ["a.JS"]


def test_js_syntax_gate_skips_when_only_deleted_js_is_touched(tmp_path: Path) -> None:
    run_js_syntax_gate = _import_run_gate()

    class DummyLogger:
        def __init__(self) -> None:
            self.warnings: list[str] = []

        def warning_core(self, msg: str) -> None:
            self.warnings.append(msg)

        def section(self, _msg: str) -> None:
            raise AssertionError("section() must not be called when JS gate is SKIP")

        def line(self, _msg: str) -> None:
            raise AssertionError("line() must not be called when JS gate is SKIP")

        def run_logged(self, _argv: list[str], *, cwd: Path):
            raise AssertionError("run_logged() must not be called when JS gate is SKIP")

    logger = DummyLogger()
    ok = run_js_syntax_gate(
        logger,  # type: ignore[arg-type]
        tmp_path,
        decision_paths=["deleted.js"],
        extensions=[".js"],
        command=["node", "--check"],
    )
    assert ok is True
    assert logger.warnings == ["gate_js=SKIP (no_existing_js_files)"]
