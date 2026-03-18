from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.cli import parse_args
    from am_patch.log import Logger

    return Logger, parse_args


def _mk_logger(tmp_path: Path, *, screen_level: str, log_level: str):
    logger_cls, _ = _import_am_patch()

    log_path = tmp_path / "am_patch.log"
    symlink_path = tmp_path / "am_patch.symlink"
    return logger_cls(
        log_path=log_path,
        symlink_path=symlink_path,
        screen_level=screen_level,
        log_level=log_level,
        symlink_enabled=False,
    )


def test_normal_shows_core_hides_detail_and_matches_log(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    logger = _mk_logger(tmp_path, screen_level="normal", log_level="normal")
    try:
        logger.emit(severity="INFO", channel="CORE", message="DO: STAGE\n")
        logger.emit(severity="INFO", channel="DETAIL", message="DIAG\n")
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = (tmp_path / "am_patch.log").read_text(encoding="utf-8")

    assert "DO: STAGE" in out
    assert "DIAG" not in out

    assert out == data


def test_error_detail_is_visible_even_in_quiet(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    logger = _mk_logger(tmp_path, screen_level="quiet", log_level="quiet")
    try:
        logger.emit(severity="INFO", channel="CORE", message="CORE\n")
        logger.emit(severity="INFO", channel="DETAIL", message="DETAIL\n")
        logger.emit(
            severity="ERROR",
            channel="CORE",
            message="[stdout]\nhello\n",
            error_detail=True,
        )
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = (tmp_path / "am_patch.log").read_text(encoding="utf-8")

    assert "CORE" not in out
    assert "DETAIL" not in out
    assert "hello" in out

    assert "CORE" not in data
    assert "DETAIL" not in data
    assert "hello" in data


def test_run_metadata_only_in_debug(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    logger_v = _mk_logger(tmp_path / "v", screen_level="verbose", log_level="verbose")
    try:
        _ = logger_v.run_logged([sys.executable, "-c", "print('ok')"], cwd=None)
    finally:
        logger_v.close()

    out_v = capsys.readouterr().out
    assert "cmd=" not in out_v

    logger_d = _mk_logger(tmp_path / "d", screen_level="debug", log_level="debug")
    try:
        _ = logger_d.run_logged([sys.executable, "-c", "print('ok')"], cwd=None)
    finally:
        logger_d.close()

    out_d = capsys.readouterr().out
    assert "cmd=" in out_d


def test_cli_accepts_warning_and_log_level():
    _, parse_args = _import_am_patch()
    ns = parse_args(["--verbosity", "warning", "--log-level", "warning", "1", "msg"])
    assert ns.verbosity == "warning"
    assert ns.log_level == "warning"


def test_subprocess_live_json_ignores_screen_level(tmp_path: Path):
    logger = _mk_logger(tmp_path, screen_level="normal", log_level="debug")
    logger.json_enabled = True
    logger.json_path = tmp_path / "am_patch.jsonl"
    logger._json_fp = logger._close_stack.enter_context(
        logger.json_path.open("w", encoding="utf-8")
    )
    try:
        logger.run_logged([sys.executable, "-c", "print('hello', flush=True)"])
    finally:
        logger.close()

    events = [
        json.loads(line)
        for line in (tmp_path / "am_patch.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(evt.get("kind") == "SUBPROCESS_STDOUT" for evt in events)


def test_live_ipc_output_arrives_before_process_exit(tmp_path: Path) -> None:
    logger = _mk_logger(tmp_path, screen_level="normal", log_level="quiet")
    events: list[dict[str, object]] = []
    logger.set_ipc_stream(events.append)
    done = threading.Event()
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            logger.run_logged(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys, time; "
                        "sys.stdout.write('first\\n'); sys.stdout.flush(); "
                        "time.sleep(0.5); "
                        "sys.stdout.write('tail'); sys.stdout.flush()"
                    ),
                ]
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    try:
        for _ in range(100):
            if any(
                evt.get("kind") == "SUBPROCESS_STDOUT" and evt.get("msg") == "first"
                for evt in events
            ):
                assert not done.is_set()
                break
            done.wait(0.05)
        else:
            raise AssertionError("missing live IPC subprocess event")
        worker.join(timeout=5.0)
        assert not worker.is_alive()
        assert not errors
        assert any(
            evt.get("kind") == "SUBPROCESS_STDOUT" and evt.get("msg") == "tail" for evt in events
        )
    finally:
        logger.close()


def test_live_screen_output_arrives_before_process_exit(tmp_path: Path) -> None:
    logger = _mk_logger(tmp_path, screen_level="verbose", log_level="quiet")
    done = threading.Event()
    saw_first = threading.Event()
    errors: list[BaseException] = []
    seen: list[str] = []

    original = logger._write_screen

    def _write_screen(s: str) -> None:
        seen.append(s)
        if "[stdout] first" in s:
            assert not done.is_set()
            saw_first.set()
        original(s)

    logger._write_screen = _write_screen  # type: ignore[method-assign]

    def _runner() -> None:
        try:
            logger.run_logged(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys, time; "
                        "sys.stdout.write('first\\n'); sys.stdout.flush(); "
                        "time.sleep(0.5); "
                        "sys.stdout.write('tail'); sys.stdout.flush()"
                    ),
                ]
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    try:
        assert saw_first.wait(timeout=5.0)
        worker.join(timeout=5.0)
        assert not worker.is_alive()
        assert not errors
        assert any("[stdout] tail" in part for part in seen)
    finally:
        logger.close()


def test_live_file_log_output_arrives_before_process_exit(tmp_path: Path) -> None:
    logger = _mk_logger(tmp_path, screen_level="quiet", log_level="verbose")
    done = threading.Event()
    saw_first = threading.Event()
    errors: list[BaseException] = []
    seen: list[str] = []

    original = logger._write_file

    def _write_file(s: str) -> None:
        seen.append(s)
        if "[stdout] first" in s:
            assert not done.is_set()
            saw_first.set()
        original(s)

    logger._write_file = _write_file  # type: ignore[method-assign]

    def _runner() -> None:
        try:
            logger.run_logged(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys, time; "
                        "sys.stdout.write('first\\n'); sys.stdout.flush(); "
                        "time.sleep(0.5); "
                        "sys.stdout.write('tail'); sys.stdout.flush()"
                    ),
                ]
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    try:
        assert saw_first.wait(timeout=5.0)
        worker.join(timeout=5.0)
        assert not worker.is_alive()
        assert not errors
        assert any("[stdout] tail" in part for part in seen)
    finally:
        logger.close()


def test_failed_step_screen_fallback_is_skipped_after_live_output(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    logger = _mk_logger(tmp_path, screen_level="verbose", log_level="quiet")
    try:
        result = logger.run_logged(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('boom\\n'); sys.exit(1)",
            ]
        )
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = (tmp_path / "am_patch.log").read_text(encoding="utf-8")

    assert result.returncode == 1
    assert "[stderr] boom" in out
    assert "FAILED STEP OUTPUT" not in out
    assert "FAILED STEP OUTPUT" in data
    assert "boom" in data


def test_failed_step_log_fallback_is_skipped_after_live_output(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    logger = _mk_logger(tmp_path, screen_level="normal", log_level="verbose")
    try:
        result = logger.run_logged(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('boom\\n'); sys.exit(1)",
            ]
        )
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = (tmp_path / "am_patch.log").read_text(encoding="utf-8")

    assert result.returncode == 1
    assert "FAILED STEP OUTPUT" in out
    assert "boom" in out
    assert "[stderr] boom" in data
    assert "FAILED STEP OUTPUT" not in data


def test_failed_step_json_payload_is_not_duplicated_after_live_stream(
    tmp_path: Path,
) -> None:
    logger = _mk_logger(tmp_path, screen_level="normal", log_level="quiet")
    logger.json_enabled = True
    logger.json_path = tmp_path / "am_patch.jsonl"
    logger._json_fp = logger._close_stack.enter_context(
        logger.json_path.open("w", encoding="utf-8")
    )
    try:
        result = logger.run_logged(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('boom\\n'); sys.exit(1)",
            ]
        )
    finally:
        logger.close()

    events = [
        json.loads(line)
        for line in (tmp_path / "am_patch.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    failed = [evt for evt in events if evt.get("msg") == "FAILED STEP OUTPUT"]

    assert result.returncode == 1
    assert any(
        evt.get("kind") == "SUBPROCESS_STDERR" and evt.get("msg") == "boom" for evt in events
    )
    assert len(failed) == 1
    assert "stdout" not in failed[0]
    assert "stderr" not in failed[0]


def test_failed_step_ipc_payload_is_not_duplicated_after_live_stream(
    tmp_path: Path,
) -> None:
    logger = _mk_logger(tmp_path, screen_level="normal", log_level="quiet")
    logger.json_enabled = True
    logger.json_path = tmp_path / "am_patch.jsonl"
    logger._json_fp = logger._close_stack.enter_context(
        logger.json_path.open("w", encoding="utf-8")
    )
    events: list[dict[str, object]] = []
    logger.set_ipc_stream(events.append)
    try:
        result = logger.run_logged(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('boom\\n'); sys.exit(1)",
            ]
        )
    finally:
        logger.close()

    failed = [evt for evt in events if evt.get("msg") == "FAILED STEP OUTPUT"]

    assert result.returncode == 1
    assert any(
        evt.get("kind") == "SUBPROCESS_STDERR" and evt.get("msg") == "boom" for evt in events
    )
    assert len(failed) == 1
    assert "stdout" not in failed[0]
    assert "stderr" not in failed[0]


def test_runner_failure_detail_and_fingerprint_bypass_quiet(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    logger = _mk_logger(tmp_path, screen_level="quiet", log_level="quiet")
    try:
        logger.emit(
            severity="ERROR",
            channel="CORE",
            message="ERROR DETAIL: PREFLIGHT:PATCH_ASCII: bad patch\n",
            error_detail=True,
        )
        logger.emit(
            severity="ERROR",
            channel="CORE",
            message=(
                "AM_PATCH_FAILURE_FINGERPRINT:\n- stage: PREFLIGHT\n- category: PATCH_ASCII\n"
            ),
            error_detail=True,
            to_screen=False,
            to_log=True,
        )
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = (tmp_path / "am_patch.log").read_text(encoding="utf-8")

    assert "ERROR DETAIL: PREFLIGHT:PATCH_ASCII: bad patch" in out
    assert "AM_PATCH_FAILURE_FINGERPRINT" not in out
    assert "ERROR DETAIL: PREFLIGHT:PATCH_ASCII: bad patch" in data
    assert "AM_PATCH_FAILURE_FINGERPRINT" in data


def test_failure_dump_breaks_active_status_line_before_screen_output(
    tmp_path: Path,
) -> None:
    logger = _mk_logger(tmp_path, screen_level="quiet", log_level="quiet")
    calls: list[str] = []
    seen: list[str] = []

    original = logger._write_screen

    def _break_line() -> None:
        calls.append("break")

    def _write_screen(s: str) -> None:
        seen.append(s)
        original(s)

    logger.set_screen_break_hook(_break_line)
    logger._write_screen = _write_screen  # type: ignore[method-assign]
    try:
        logger.run_logged(
            [
                sys.executable,
                "-c",
                ("import sys; sys.stderr.write('boom\n'); sys.stderr.flush(); raise SystemExit(1)"),
            ]
        )
    finally:
        logger.close()

    assert calls == ["break"]
    assert seen
    assert seen[0].startswith("\n" + ("=" * 80))
    assert any(part == "[stderr]\n" for part in seen)
    assert any("boom\n" in part for part in seen)


def test_result_event_with_terminal_fields_keeps_ndjson_valid_after_live_stream(
    tmp_path: Path,
) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.final_summary import build_terminal_summary

    logger = _mk_logger(tmp_path, screen_level="normal", log_level="debug")
    logger.json_enabled = True
    logger.json_path = tmp_path / "am_patch.jsonl"
    logger._json_fp = logger._close_stack.enter_context(
        logger.json_path.open("w", encoding="utf-8")
    )
    try:
        logger.run_logged([sys.executable, "-c", "print('hello', flush=True)"])
        logger.emit_json_result(
            summary=build_terminal_summary(
                exit_code=0,
                commit_and_push=False,
                final_commit_sha=None,
                final_pushed_files=None,
                push_ok_for_posthook=None,
                final_fail_stage=None,
                final_fail_reason=None,
                log_path=tmp_path / "am_patch.log",
                json_path=tmp_path / "am_patch.jsonl",
            )
        )
    finally:
        logger.close()

    events = [
        json.loads(line)
        for line in (tmp_path / "am_patch.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    result_evt = next(evt for evt in events if evt.get("type") == "result")

    assert any(evt.get("kind") == "SUBPROCESS_STDOUT" for evt in events)
    assert result_evt["terminal_status"] == "success"
    assert result_evt["final_stage"] is None
    assert result_evt["final_reason"] is None
    assert result_evt["json_path"] == str(tmp_path / "am_patch.jsonl")
