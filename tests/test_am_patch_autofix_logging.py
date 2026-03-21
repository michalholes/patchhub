from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _import_am_patch_modules():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.gate_step_capture import capture_gate_step
    from am_patch.gates import run_biome, run_ruff
    from am_patch.log import Logger, RunResult

    return Logger, RunResult, capture_gate_step, run_biome, run_ruff


def _mk_logger(tmp_path: Path, *, screen_level: str, log_level: str):
    logger_cls, _, _, _, _ = _import_am_patch_modules()
    log_path = tmp_path / "am_patch.log"
    symlink_path = tmp_path / "am_patch.symlink"
    return logger_cls(
        log_path=log_path,
        symlink_path=symlink_path,
        screen_level=screen_level,
        log_level=log_level,
        symlink_enabled=False,
    )


def test_run_logged_diagnostic_detail_omits_failed_step_output(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    logger = _mk_logger(tmp_path, screen_level="warning", log_level="warning")
    try:
        result = logger.run_logged(
            [
                sys.executable,
                "-c",
                (
                    "import sys; print('fixable stdout'); "
                    "sys.stderr.write('fixable stderr\n'); sys.exit(1)"
                ),
            ],
            failure_dump_mode="diagnostic_detail",
        )
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = (tmp_path / "am_patch.log").read_text(encoding="utf-8")

    assert result.returncode == 1
    assert "FAILED STEP OUTPUT" not in out
    assert "FAILED STEP OUTPUT" not in data
    assert "fixable stdout" in out
    assert "fixable stderr" in out


def test_run_logged_warn_detail_still_emits_failed_step_output(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    logger = _mk_logger(tmp_path, screen_level="warning", log_level="warning")
    try:
        result = logger.run_logged(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('boom\n'); sys.exit(1)",
            ],
            failure_dump_mode="warn_detail",
        )
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = (tmp_path / "am_patch.log").read_text(encoding="utf-8")

    assert result.returncode == 1
    assert "FAILED STEP OUTPUT" in out
    assert "FAILED STEP OUTPUT" in data


class _RecordingLogger:
    def __init__(self, run_results):
        self.run_results = list(run_results)
        self.calls = []
        self.sections = []
        self.lines = []
        self.warnings = []

    def section(self, title: str) -> None:
        self.sections.append(title)

    def line(self, msg: str) -> None:
        self.lines.append(msg)

    def warning_core(self, msg: str) -> None:
        self.warnings.append(msg)

    def run_logged(self, argv, cwd=None, env=None, **kwargs):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "env": env,
                "kwargs": dict(kwargs),
            }
        )
        result = self.run_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def test_run_ruff_uses_diagnostic_mode_only_for_initial_autofix_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, run_result_cls, _, _, run_ruff = _import_am_patch_modules()
    logger = _RecordingLogger(
        [
            run_result_cls(
                argv=["ruff", "check"],
                returncode=1,
                stdout="fixable\n",
                stderr="",
            ),
            run_result_cls(
                argv=["ruff", "check", "--fix"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            run_result_cls(
                argv=["ruff", "check"],
                returncode=1,
                stdout="",
                stderr="still bad\n",
            ),
        ]
    )

    monkeypatch.setattr(
        "am_patch.gates._select_python_for_gate",
        lambda **_kwargs: sys.executable,
    )
    monkeypatch.setattr("am_patch.gate_step_capture.changed_paths", lambda *_a, **_k: [])

    ok = run_ruff(
        logger,
        tmp_path,
        repo_root=tmp_path,
        ruff_format=False,
        autofix=True,
        targets=["tests"],
    )

    assert ok is False
    assert logger.calls[0]["kwargs"]["failure_dump_mode"] == "diagnostic_detail"
    assert logger.calls[1]["kwargs"]["failure_dump_mode"] == "warn_detail"
    assert "failure_dump_mode" not in logger.calls[2]["kwargs"]


def test_run_biome_uses_diagnostic_mode_only_for_initial_autofix_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, run_result_cls, _, run_biome, _ = _import_am_patch_modules()
    target = tmp_path / "demo.js"
    target.write_text("console.log('x');\n", encoding="utf-8")
    logger = _RecordingLogger(
        [
            run_result_cls(
                argv=["biome", "check"],
                returncode=1,
                stdout="fixable\n",
                stderr="",
            ),
            run_result_cls(
                argv=["biome", "check", "--write"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            run_result_cls(
                argv=["biome", "check"],
                returncode=1,
                stdout="",
                stderr="still bad\n",
            ),
        ]
    )

    monkeypatch.setattr("am_patch.gate_step_capture.changed_paths", lambda *_a, **_k: [])

    ok = run_biome(
        logger,
        tmp_path,
        decision_paths=["demo.js"],
        extensions=[".js"],
        command=["biome", "check"],
        biome_format=False,
        format_command=["biome", "format", "--write"],
        autofix=True,
        fix_command=["biome", "check", "--write"],
    )

    assert ok is False
    assert logger.calls[0]["kwargs"]["failure_dump_mode"] == "diagnostic_detail"
    assert logger.calls[1]["kwargs"]["failure_dump_mode"] == "warn_detail"
    assert "failure_dump_mode" not in logger.calls[2]["kwargs"]


def test_run_ruff_emits_step_logs_and_callbacks_for_format_and_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run_result_cls, _, _, run_ruff = _import_am_patch_modules()
    logger = _RecordingLogger(
        [
            run_result_cls(
                argv=["ruff", "format"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            run_result_cls(
                argv=["ruff", "check"],
                returncode=1,
                stdout="fixable\n",
                stderr="",
            ),
            run_result_cls(
                argv=["ruff", "check", "--fix"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            run_result_cls(
                argv=["ruff", "check"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]
    )
    callbacks: list[tuple[str, list[str], list[str]]] = []
    snapshots = iter(
        [
            ["declared.py"],
            ["declared.py", "tests/formatted.py"],
            ["declared.py", "tests/formatted.py"],
            ["declared.py", "tests/fixed.py", "tests/formatted.py"],
        ]
    )

    monkeypatch.setattr(
        "am_patch.gates._select_python_for_gate",
        lambda **_kwargs: sys.executable,
    )
    monkeypatch.setattr(
        "am_patch.gate_step_capture.changed_paths",
        lambda *_args, **_kwargs: list(next(snapshots)),
    )

    ok = run_ruff(
        logger,
        tmp_path,
        repo_root=tmp_path,
        ruff_format=True,
        autofix=True,
        targets=["tests"],
        gate_step_callback=lambda **kwargs: callbacks.append(
            (kwargs["step_key"], kwargs["pre_dirty"], kwargs["post_dirty"])
        ),
    )

    assert ok is True
    assert logger.lines == [
        "gate_step_pre_dirty_ruff_format=['declared.py']",
        "gate_step_post_dirty_ruff_format=['declared.py', 'tests/formatted.py']",
        "gate_step_delta_ruff_format=['tests/formatted.py']",
        "gate_step_pre_dirty_ruff_fix=['declared.py', 'tests/formatted.py']",
        "gate_step_post_dirty_ruff_fix=['declared.py', 'tests/fixed.py', 'tests/formatted.py']",
        "gate_step_delta_ruff_fix=['tests/fixed.py']",
    ]
    assert callbacks == [
        ("ruff_format", ["declared.py"], ["declared.py", "tests/formatted.py"]),
        (
            "ruff_fix",
            ["declared.py", "tests/formatted.py"],
            ["declared.py", "tests/fixed.py", "tests/formatted.py"],
        ),
    ]
    assert logger.calls[0]["kwargs"]["failure_dump_mode"] == "warn_detail"
    assert logger.calls[1]["kwargs"]["failure_dump_mode"] == "diagnostic_detail"
    assert logger.calls[2]["kwargs"]["failure_dump_mode"] == "warn_detail"
    assert "failure_dump_mode" not in logger.calls[3]["kwargs"]


def test_run_ruff_failed_format_still_emits_step_logs_and_callback_before_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run_result_cls, _, _, run_ruff = _import_am_patch_modules()
    logger = _RecordingLogger(
        [
            run_result_cls(
                argv=["ruff", "format"],
                returncode=1,
                stdout="",
                stderr="format failed\n",
            )
        ]
    )
    callbacks: list[tuple[str, list[str], list[str]]] = []
    snapshots = iter([["declared.py"], ["declared.py", "tests/formatted.py"]])

    monkeypatch.setattr(
        "am_patch.gates._select_python_for_gate",
        lambda **_kwargs: sys.executable,
    )
    monkeypatch.setattr(
        "am_patch.gate_step_capture.changed_paths",
        lambda *_args, **_kwargs: list(next(snapshots)),
    )

    ok = run_ruff(
        logger,
        tmp_path,
        repo_root=tmp_path,
        ruff_format=True,
        autofix=False,
        targets=["tests"],
        gate_step_callback=lambda **kwargs: callbacks.append(
            (kwargs["step_key"], kwargs["pre_dirty"], kwargs["post_dirty"])
        ),
    )

    assert ok is False
    assert logger.lines == [
        "gate_step_pre_dirty_ruff_format=['declared.py']",
        "gate_step_post_dirty_ruff_format=['declared.py', 'tests/formatted.py']",
        "gate_step_delta_ruff_format=['tests/formatted.py']",
    ]
    assert callbacks == [("ruff_format", ["declared.py"], ["declared.py", "tests/formatted.py"])]
    assert logger.calls[0]["kwargs"]["failure_dump_mode"] == "warn_detail"


def test_run_ruff_preserves_original_cancel_when_callback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, _, run_ruff = _import_am_patch_modules()
    from am_patch.errors import RunnerCancelledError

    logger = _RecordingLogger([RunnerCancelledError("GATES", "subprocess canceled (ruff)")])
    snapshots = iter([["declared.py"], ["declared.py", "tests/formatted.py"]])

    monkeypatch.setattr(
        "am_patch.gates._select_python_for_gate",
        lambda **_kwargs: sys.executable,
    )
    monkeypatch.setattr(
        "am_patch.gate_step_capture.changed_paths",
        lambda *_args, **_kwargs: list(next(snapshots)),
    )

    def _fail_callback(**_kwargs) -> None:
        raise ValueError("cbfail")

    with pytest.raises(RunnerCancelledError) as exc_info:
        run_ruff(
            logger,
            tmp_path,
            repo_root=tmp_path,
            ruff_format=True,
            autofix=False,
            targets=["tests"],
            gate_step_callback=_fail_callback,
        )

    assert str(exc_info.value) == "GATES:CANCELED: subprocess canceled (ruff)"
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "cbfail"
    assert logger.lines == [
        "gate_step_pre_dirty_ruff_format=['declared.py']",
        "gate_step_post_dirty_ruff_format=['declared.py', 'tests/formatted.py']",
        "gate_step_delta_ruff_format=['tests/formatted.py']",
    ]


def test_run_biome_emits_step_logs_and_callbacks_for_format_and_autofix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run_result_cls, _, run_biome, _ = _import_am_patch_modules()
    target = tmp_path / "demo.js"
    target.write_text("console.log('x');\n", encoding="utf-8")
    logger = _RecordingLogger(
        [
            run_result_cls(
                argv=["biome", "format", "--write"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            run_result_cls(
                argv=["biome", "check"],
                returncode=1,
                stdout="fixable\n",
                stderr="",
            ),
            run_result_cls(
                argv=["biome", "check", "--write"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            run_result_cls(
                argv=["biome", "check"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]
    )
    callbacks: list[tuple[str, list[str], list[str]]] = []
    snapshots = iter(
        [
            ["declared.py"],
            ["declared.py", "demo.js"],
            ["declared.py", "demo.js"],
            ["declared.py", "demo.fixed.js", "demo.js"],
        ]
    )

    monkeypatch.setattr(
        "am_patch.gate_step_capture.changed_paths",
        lambda *_args, **_kwargs: list(next(snapshots)),
    )

    ok = run_biome(
        logger,
        tmp_path,
        decision_paths=["demo.js"],
        extensions=[".js"],
        command=["biome", "check"],
        biome_format=True,
        format_command=["biome", "format", "--write"],
        autofix=True,
        fix_command=["biome", "check", "--write"],
        gate_step_callback=lambda **kwargs: callbacks.append(
            (kwargs["step_key"], kwargs["pre_dirty"], kwargs["post_dirty"])
        ),
    )

    assert ok is True
    assert logger.lines == [
        "gate_biome_format_cmd=biome format --write",
        "gate_step_pre_dirty_biome_format=['declared.py']",
        "gate_step_post_dirty_biome_format=['declared.py', 'demo.js']",
        "gate_step_delta_biome_format=['demo.js']",
        "gate_biome_extensions=.js",
        "gate_biome_cmd=biome check",
        "gate_biome_file=demo.js",
        "gate_biome_fix_cmd=biome check --write",
        "gate_step_pre_dirty_biome_autofix=['declared.py', 'demo.js']",
        "gate_step_post_dirty_biome_autofix=['declared.py', 'demo.fixed.js', 'demo.js']",
        "gate_step_delta_biome_autofix=['demo.fixed.js']",
    ]
    assert callbacks == [
        ("biome_format", ["declared.py"], ["declared.py", "demo.js"]),
        (
            "biome_autofix",
            ["declared.py", "demo.js"],
            ["declared.py", "demo.fixed.js", "demo.js"],
        ),
    ]
    assert logger.calls[0]["kwargs"]["failure_dump_mode"] == "warn_detail"
    assert logger.calls[1]["kwargs"]["failure_dump_mode"] == "diagnostic_detail"
    assert logger.calls[2]["kwargs"]["failure_dump_mode"] == "warn_detail"
    assert "failure_dump_mode" not in logger.calls[3]["kwargs"]
