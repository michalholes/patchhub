"""Tests for centralized logging system."""

from __future__ import annotations

from audiomason.core.log_bus import LogRecord, get_log_bus
from audiomason.core.logging import (
    VerbosityLevel,
    get_logger,
    get_verbosity,
    set_colors,
    set_log_sink,
    set_verbosity,
)


class TestVerbosityLevel:
    """Test VerbosityLevel enum."""

    def test_verbosity_values(self):
        """Test verbosity level values."""
        assert VerbosityLevel.QUIET == 0
        assert VerbosityLevel.NORMAL == 1
        assert VerbosityLevel.VERBOSE == 2
        assert VerbosityLevel.DEBUG == 3

    def test_verbosity_ordering(self):
        """Test verbosity level ordering."""
        assert VerbosityLevel.QUIET < VerbosityLevel.NORMAL
        assert VerbosityLevel.NORMAL < VerbosityLevel.VERBOSE
        assert VerbosityLevel.VERBOSE < VerbosityLevel.DEBUG


class TestLoggingSetup:
    """Test logging setup functions."""

    def test_set_get_verbosity(self):
        """Test setting and getting verbosity."""
        set_verbosity(2)
        assert get_verbosity() == VerbosityLevel.VERBOSE

        set_verbosity(VerbosityLevel.DEBUG)
        assert get_verbosity() == VerbosityLevel.DEBUG

        set_verbosity(VerbosityLevel.NORMAL)

    def test_set_colors(self):
        """Test setting colors."""
        set_colors(False)
        logger = get_logger("test")
        logger.info("test")

        set_colors(True)


def test_log_bus_no_subscribers_no_crash() -> None:
    bus = get_log_bus()
    bus.clear()

    logger = get_logger("logbus_test")
    logger.info("hello")


def test_log_bus_subscribe_all_receives_record_plain() -> None:
    bus = get_log_bus()
    bus.clear()

    collected: list[LogRecord] = []

    def _collect(rec: LogRecord) -> None:
        collected.append(rec)

    bus.subscribe_all(_collect)

    logger = get_logger("logbus_test")
    logger.info("hello")

    assert len(collected) == 1
    assert collected[0].plain == "[info] hello"
    assert collected[0].logger_name == "logbus_test"


def test_log_bus_subscribe_level_filters() -> None:
    bus = get_log_bus()
    bus.clear()

    collected: list[LogRecord] = []

    def _collect(rec: LogRecord) -> None:
        collected.append(rec)

    bus.subscribe("ERROR", _collect)

    logger = get_logger("logbus_test")
    logger.info("hello")
    logger.error("boom")

    assert [r.level_name for r in collected] == ["ERROR"]
    assert collected[0].plain == "[error] boom"


def test_log_bus_callback_exception_is_suppressed() -> None:
    bus = get_log_bus()
    bus.clear()

    def _boom(_rec: LogRecord) -> None:
        raise RuntimeError("fail")

    bus.subscribe_all(_boom)

    logger = get_logger("logbus_test")
    logger.info("hello")


def test_set_log_sink_adapter_receives_plain_and_can_be_removed() -> None:
    bus = get_log_bus()
    bus.clear()

    received: list[str] = []

    def _sink(line: str) -> None:
        received.append(line)

    set_log_sink(_sink)

    logger = get_logger("logbus_test")
    logger.info("hello")

    assert received == ["[info] hello"]

    set_log_sink(None)
    logger.info("second")

    assert received == ["[info] hello"]

    # Ensure tests do not leak global sink state.
    bus.clear()
    set_log_sink(None)
