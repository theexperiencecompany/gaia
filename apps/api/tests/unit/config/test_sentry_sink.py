"""Tests for the Sentry loguru sink's event filtering.

The sink forwards ERROR+ loguru records to Sentry, but must NOT forward the
generic wide-event boundary roll-ups: the per-request "http_request" (logger
REQUEST), the worker/background boundary events (loggers WORKER/BG), and the
boundary's own constant "task failed" line. Each of those has a constant
message, so forwarding them collapses every unrelated failure into one useless
Sentry issue — the real per-task cause is logged with its own specific message
elsewhere and reaches Sentry on its own. This mirrors the long-standing
suppression of the HTTP request roll-up.
"""

from types import SimpleNamespace
from unittest.mock import patch

from app.config.loggers import REQUEST_LOGGER_NAME
from app.config.sentry import _make_sentry_loguru_sink
from shared.py.wide_events import (
    BACKGROUND_LOGGER_NAME,
    BOUNDARY_FAILURE_MESSAGE,
    WORKER_EVENT_NAME,
    WORKER_LOGGER_NAME,
)


def _record(
    *,
    level_no: int = 40,
    level_name: str = "ERROR",
    message: str = "boom",
    logger_name: str = "APP",
    module: str = "some_module",
) -> SimpleNamespace:
    """Build a minimal stand-in for the loguru Message the sink receives."""
    return SimpleNamespace(
        record={
            "level": SimpleNamespace(no=level_no, name=level_name),
            "extra": {"logger_name": logger_name},
            "exception": None,
            "module": module,
            "message": message,
        }
    )


def _run_sink(record: SimpleNamespace):
    sink = _make_sentry_loguru_sink()
    with (
        patch("app.config.sentry.sentry_sdk.capture_message") as cap_msg,
        patch("app.config.sentry.sentry_sdk.capture_exception") as cap_exc,
        patch("app.config.sentry.sentry_sdk.new_scope"),
    ):
        sink(record)
    return cap_msg, cap_exc


def test_forwards_specific_error_to_sentry():
    cap_msg, cap_exc = _run_sink(_record(message="Executor run failed", logger_name="APP"))
    cap_msg.assert_called_once()


def test_skips_http_request_rollup():
    cap_msg, cap_exc = _run_sink(_record(message="http_request", logger_name=REQUEST_LOGGER_NAME))
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_skips_worker_boundary_rollup():
    cap_msg, cap_exc = _run_sink(_record(message=WORKER_EVENT_NAME, logger_name=WORKER_LOGGER_NAME))
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_skips_background_boundary_rollup():
    cap_msg, cap_exc = _run_sink(
        _record(message="background_task", logger_name=BACKGROUND_LOGGER_NAME)
    )
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_skips_boundary_task_failed_line():
    # The "task failed" line is emitted with the default logger_name, so it is
    # suppressed by message, not logger.
    cap_msg, cap_exc = _run_sink(_record(message=BOUNDARY_FAILURE_MESSAGE, logger_name="APP"))
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_skips_below_error_level():
    cap_msg, cap_exc = _run_sink(
        _record(level_no=30, level_name="WARNING", message="just a warning")
    )
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()
