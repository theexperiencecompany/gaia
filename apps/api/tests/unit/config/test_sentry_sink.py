"""Tests for the Sentry loguru sink's event filtering and scope tagging.

The sink forwards ERROR+ loguru records to Sentry, but must NOT forward the
generic wide-event boundary roll-ups: the per-request "http_request" (logger
REQUEST), the worker/background boundary events (loggers WORKER/BG), and the
boundary's own constant "task failed" line. Each of those has a constant
message, so forwarding them collapses every unrelated failure into one useless
Sentry issue; the real per-task cause is logged with its own specific message
elsewhere and reaches Sentry on its own. This mirrors the long-standing
suppression of the HTTP request roll-up. The forwarded path also stamps the
scope (logger/module tags, PII-scrubbed extras) and picks the capture level.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    logger_name: str | None = "APP",
    module: str = "some_module",
    extra: dict[str, object] | None = None,
    exception: object | None = None,
) -> SimpleNamespace:
    """Build a minimal stand-in for the loguru Message the sink receives."""
    extra_fields: dict[str, object] = {"logger_name": logger_name} if logger_name else {}
    if extra:
        extra_fields.update(extra)
    return SimpleNamespace(
        record={
            "level": SimpleNamespace(no=level_no, name=level_name),
            "extra": extra_fields,
            "exception": exception,
            "module": module,
            "message": message,
        }
    )


def _run_sink(record: SimpleNamespace) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Run the sink, returning (capture_message, capture_exception, scope) mocks."""
    sink = _make_sentry_loguru_sink()
    scope = MagicMock()
    scope_cm = MagicMock()
    scope_cm.__enter__.return_value = scope
    scope_cm.__exit__.return_value = False
    with (
        patch("app.config.sentry.sentry_sdk.capture_message") as cap_msg,
        patch("app.config.sentry.sentry_sdk.capture_exception") as cap_exc,
        patch("app.config.sentry.sentry_sdk.new_scope", return_value=scope_cm),
    ):
        sink(record)
    return cap_msg, cap_exc, scope


def test_forwards_specific_error_to_sentry() -> None:
    cap_msg, _cap_exc, _scope = _run_sink(_record(message="Executor run failed", logger_name="APP"))
    cap_msg.assert_called_once()
    # Message and level are forwarded verbatim for a non-exception record.
    args, kwargs = cap_msg.call_args
    assert args[0] == "Executor run failed"
    assert kwargs["level"] == "error"


def test_critical_record_forwards_as_fatal() -> None:
    cap_msg, _cap_exc, _scope = _run_sink(
        _record(level_name="CRITICAL", message="meltdown", logger_name="APP")
    )
    _, kwargs = cap_msg.call_args
    assert kwargs["level"] == "fatal"


def test_exception_record_captures_the_exception_not_a_message() -> None:
    exc = ValueError("boom")
    cap_msg, cap_exc, _scope = _run_sink(
        _record(message="handler failed", exception=SimpleNamespace(value=exc))
    )
    cap_exc.assert_called_once_with(exc)
    cap_msg.assert_not_called()


def test_scope_is_tagged_with_logger_and_module() -> None:
    _cap_msg, _cap_exc, scope = _run_sink(_record(logger_name="AUTH", module="auth_module"))
    scope.set_tag.assert_any_call("logger", "AUTH")
    scope.set_tag.assert_any_call("module", "auth_module")


def test_logger_tag_falls_back_to_app_when_absent() -> None:
    _cap_msg, _cap_exc, scope = _run_sink(_record(logger_name=None))
    scope.set_tag.assert_any_call("logger", "app")


def test_scope_extras_exclude_logger_name_and_pii() -> None:
    _cap_msg, _cap_exc, scope = _run_sink(
        _record(
            logger_name="APP",
            extra={"trace_id": "t1", "email": "a@b.com", "count": 3},
        )
    )
    extra_keys = {call.args[0] for call in scope.set_extra.call_args_list}
    assert "trace_id" in extra_keys
    assert "count" in extra_keys
    # logger_name is a tag, never an extra; email is PII and is scrubbed.
    assert "logger_name" not in extra_keys
    assert "email" not in extra_keys


def test_skips_http_request_rollup() -> None:
    cap_msg, cap_exc, _scope = _run_sink(
        _record(message="http_request", logger_name=REQUEST_LOGGER_NAME)
    )
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_skips_worker_boundary_rollup() -> None:
    cap_msg, cap_exc, _scope = _run_sink(
        _record(message=WORKER_EVENT_NAME, logger_name=WORKER_LOGGER_NAME)
    )
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_skips_background_boundary_rollup() -> None:
    cap_msg, cap_exc, _scope = _run_sink(
        _record(message="background_task", logger_name=BACKGROUND_LOGGER_NAME)
    )
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_skips_boundary_task_failed_line() -> None:
    # The "task failed" line is emitted with the default logger_name, so it is
    # suppressed by message, not logger.
    cap_msg, cap_exc, _scope = _run_sink(
        _record(message=BOUNDARY_FAILURE_MESSAGE, logger_name="APP")
    )
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_boundary_task_failed_with_exception_is_still_captured() -> None:
    # A boundary that raised before logging a specific error attaches the
    # exception to its "task failed" line; that must still reach Sentry as the
    # exception (grouped by traceback), not be swallowed with the aggregate.
    exc = RuntimeError("boom")
    cap_msg, cap_exc, _scope = _run_sink(
        _record(
            message=BOUNDARY_FAILURE_MESSAGE,
            logger_name="APP",
            exception=SimpleNamespace(value=exc),
        )
    )
    cap_exc.assert_called_once_with(exc)
    cap_msg.assert_not_called()


def test_skips_below_error_level() -> None:
    cap_msg, cap_exc, _scope = _run_sink(
        _record(level_no=30, level_name="WARNING", message="just a warning")
    )
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()
