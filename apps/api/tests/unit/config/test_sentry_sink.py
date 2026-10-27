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

from collections.abc import Iterator
from contextlib import contextmanager
import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.outputs import ChatResult
from mcp_use.client.connectors.http import HttpConnector
import pytest
import sentry_sdk
from sentry_sdk.consts import OP
from sentry_sdk.integrations.langchain import LangchainIntegration
from sentry_sdk.types import Event, Hint

from app.config import sentry as sentry_config
from app.config.loggers import REQUEST_LOGGER_NAME
from app.config.sentry import _make_sentry_loguru_sink
from shared.py.logging import MCP_USE_LOGGER_DISPLAY_NAME, _InterceptHandler, env_context
from shared.py.wide_events import (
    BACKGROUND_LOGGER_NAME,
    BOUNDARY_FAILURE_MESSAGE,
    WORKER_EVENT_NAME,
    WORKER_LOGGER_NAME,
    log,
    log_context,
)
from tests.helpers import pick_free_port


def _record(
    *,
    message: str = "boom",
    logger_name: str | None = "APP",
    level: tuple[str, int] = ("ERROR", 40),
    extra: dict[str, object] | None = None,
    exception: object | None = None,
) -> SimpleNamespace:
    """Build a minimal stand-in for the loguru Message the sink receives."""
    level_name, level_no = level
    extra_fields: dict[str, object] = {"logger_name": logger_name} if logger_name else {}
    if extra:
        extra_fields.update(extra)
    return SimpleNamespace(
        record={
            "level": SimpleNamespace(no=level_no, name=level_name),
            "extra": extra_fields,
            "exception": exception,
            "module": "some_module",
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
        _record(level=("CRITICAL", 50), message="meltdown", logger_name="APP")
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
    _cap_msg, _cap_exc, scope = _run_sink(_record(logger_name="AUTH"))
    scope.set_tag.assert_any_call("logger", "AUTH")
    scope.set_tag.assert_any_call("module", "some_module")


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
    cap_msg, cap_exc, _scope = _run_sink(_record(level=("WARNING", 30), message="just a warning"))
    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


@contextmanager
def _intercepted_stdlib_logger(name: str) -> Iterator[logging.Logger]:
    """Route a stdlib logger into loguru the way configure_loguru routes the root logger."""
    stdlib_logger = logging.getLogger(name)
    handler = _InterceptHandler()
    stdlib_logger.addHandler(handler)
    stdlib_logger.propagate = False
    try:
        yield stdlib_logger
    finally:
        stdlib_logger.removeHandler(handler)
        stdlib_logger.propagate = True


class _ProviderRateLimitedError(Exception):
    """Stands in for an upstream 429 such as OpenRouter's TooManyRequestsResponseError."""


class _RateLimitedChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "rate-limited"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise _ProviderRateLimitedError("Provider returned error")


@pytest.mark.regression
def test_one_logged_error_reaches_sentry_exactly_once(sentry_events: list[Event]) -> None:
    log.error("executor run failed", error_type="RuntimeError")

    assert len(sentry_events) == 1


@pytest.mark.regression
def test_a_library_error_log_reaches_sentry_exactly_once(sentry_events: list[Event]) -> None:
    with _intercepted_stdlib_logger("tests.some_library") as library_logger:
        library_logger.error("broker connection lost")

    assert len(sentry_events) == 1


@pytest.mark.regression
async def test_an_unreachable_mcp_server_reports_once_not_per_transport(
    sentry_events: list[Event],
) -> None:
    """Transport lines are duplicates of GAIA's report; the session-task line is not."""
    with pytest.raises(httpx.ConnectError):
        await HttpConnector(f"http://127.0.0.1:{pick_free_port()}/mcp").connect()

    messages = [
        str(event.get("message") or event.get("logentry", {}).get("message", ""))
        for event in sentry_events
    ]
    assert len(sentry_events) == 1, messages
    assert "transport" not in messages[0].lower()
    assert "SseConnectionManager" in messages[0]


@pytest.mark.regression
def test_a_failed_llm_attempt_is_left_to_the_retry_policy(sentry_events: list[Event]) -> None:
    # ainvoke_llm retries or falls back on this; the caller reports it only if the policy gives up.
    with sentry_sdk.start_transaction(name="chat turn"):
        with pytest.raises(_ProviderRateLimitedError):
            _RateLimitedChatModel().invoke([HumanMessage(content="suggest follow-ups")])

    assert sentry_events == []


def test_an_exception_outside_an_llm_call_still_reaches_sentry(sentry_events: list[Event]) -> None:
    with sentry_sdk.start_transaction(name="chat turn"):
        sentry_sdk.capture_exception(_ProviderRateLimitedError("Provider returned error"))

    assert len(sentry_events) == 1


def test_a_sentry_event_names_the_service_that_sent_it(sentry_events: list[Event]) -> None:
    """The API and the ARQ worker share one Sentry project; only this tag tells them apart."""
    log.error("executor run failed", error_type="RuntimeError")

    assert [event["tags"]["service"] for event in sentry_events] == [env_context().service]


@pytest.mark.parametrize(
    ("origin", "op", "dropped"),
    [
        (LangchainIntegration.origin, OP.GEN_AI_CHAT, True),
        (LangchainIntegration.origin, OP.GEN_AI_EXECUTE_TOOL, False),
        ("manual", OP.GEN_AI_CHAT, False),
    ],
)
def test_only_an_error_captured_inside_a_langchain_model_call_is_dropped(
    origin: str, op: str, dropped: bool
) -> None:
    event: Event = {"contexts": {"trace": {"origin": origin, "op": op}}}

    assert (sentry_config._drop_llm_attempt_errors(event, {}) is None) is dropped


@pytest.mark.parametrize(("env", "rate"), [("production", 0.1), ("development", 1.0)])
def test_only_production_samples_traces_and_profiles(
    env: str, rate: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sentry_config.settings, "ENV", env)
    monkeypatch.setattr(sentry_config.settings, "AUTH_MODE", "workos")
    with (
        patch.object(sentry_config.settings, "SENTRY_DSN", "https://public@sentry.invalid/1"),
        patch.object(sentry_config, "_loguru"),
    ):
        sentry_config.init_sentry()
    options = sentry_sdk.get_client().options
    global_scope = sentry_sdk.get_global_scope()
    global_scope.clear()
    global_scope.set_client(None)

    assert (options["traces_sample_rate"], options["profiles_sample_rate"]) == (rate, rate)


@pytest.mark.regression
def test_an_mcp_connect_duplicate_does_not_reach_sentry() -> None:
    """MCPClient.connect reports the same failure with the integration id."""
    cap_msg, cap_exc, _scope = _run_sink(
        _record(
            message="MCP protocol error during initialization: code=-32601 message='Method not found'",
            logger_name=MCP_USE_LOGGER_DISPLAY_NAME,
        )
    )

    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


@pytest.mark.regression
def test_an_mcp_background_session_error_still_reaches_sentry() -> None:
    """The library's task failure has no caller in app/, so it must reach Sentry."""
    cap_msg, _cap_exc, _scope = _run_sink(
        _record(
            message="Error in SseConnectionManager task: unhandled errors in a TaskGroup",
            logger_name=MCP_USE_LOGGER_DISPLAY_NAME,
        )
    )

    cap_msg.assert_called_once()


@pytest.mark.parametrize(
    "message",
    [
        "OAuth initialization failed: no token",
        "MCP protocol error during initialization: code=-32601 message='Method not found'",
        "Failed to connect to stdio MCP server",
        "Both transport methods failed. Streamable HTTP: closed, SSE: failed",
    ],
)
def test_every_connect_transport_line_is_a_duplicate(message: str) -> None:
    """Each of these is re-raised to MCPClient.connect, which reports it with the id."""
    cap_msg, cap_exc, _scope = _run_sink(
        _record(message=message, logger_name=MCP_USE_LOGGER_DISPLAY_NAME)
    )

    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_a_swallowed_tool_listing_failure_still_reaches_sentry() -> None:
    """mcp_use catches this one and returns an empty list, so GAIA never re-reports it."""
    cap_msg, _cap_exc, _scope = _run_sink(
        _record(
            message="Error listing tools for connector https://mcp.example: boom",
            logger_name=MCP_USE_LOGGER_DISPLAY_NAME,
        )
    )

    cap_msg.assert_called_once()


def _event(**overrides: object) -> Event:
    """Build a minimal message event, shaped like what capture_message builds."""
    return cast("Event", {"logentry": {"message": "boom"}, **overrides})


def test_a_wide_event_user_becomes_the_sentry_user() -> None:
    event = sentry_config._before_send(
        _event(extra={"user": {"id": "67bdb4367c7dd1f0ea343216"}}), {}
    )

    assert event is not None
    assert event["user"] == {"id": "67bdb4367c7dd1f0ea343216"}


def test_the_user_falls_back_to_a_flat_user_id() -> None:
    event = sentry_config._before_send(_event(extra={"user_id": "67bdb4367c7dd1f0ea343216"}), {})

    assert event is not None
    assert event["user"] == {"id": "67bdb4367c7dd1f0ea343216"}


def test_an_event_without_a_user_stays_anonymous() -> None:
    event = sentry_config._before_send(_event(extra={"trace_id": "t1"}), {})

    assert event is not None
    assert "user" not in event


def test_two_messages_differing_only_by_identifiers_share_a_fingerprint() -> None:
    first = sentry_config._before_send(
        _event(
            tags={"logger": "APP"},
            logentry={"message": "MCP DCR failed for https://x.dev/u/67bdb4367c7dd1f0ea343216"},
        ),
        {},
    )
    second = sentry_config._before_send(
        _event(
            tags={"logger": "APP"},
            logentry={"message": "MCP DCR failed for https://y.dev/u/aaaaaaaaaaaaaaaaaaaa"},
        ),
        {},
    )

    assert first is not None and second is not None
    assert first["fingerprint"] == second["fingerprint"]


def test_different_messages_keep_different_fingerprints() -> None:
    first = sentry_config._before_send(_event(logentry={"message": "redis unreachable"}), {})
    second = sentry_config._before_send(_event(logentry={"message": "mongo unreachable"}), {})

    assert first is not None and second is not None
    assert first["fingerprint"] != second["fingerprint"]


def test_a_message_fingerprint_names_the_logger_that_said_it() -> None:
    event = sentry_config._before_send(_event(tags={"logger": "MCP_USE"}), {})

    assert event is not None
    assert event["fingerprint"][1] == "MCP_USE"


def test_an_exception_event_is_grouped_by_its_stack_not_its_message() -> None:
    event = sentry_config._before_send(
        _event(exception={"values": []}, logentry={"message": "boom 12"}), {}
    )

    assert event is not None
    assert "fingerprint" not in event


def test_a_retried_llm_attempt_is_dropped_before_anything_else() -> None:
    trace = {
        "origin": LangchainIntegration.origin,
        "op": OP.GEN_AI_CHAT,
    }
    assert sentry_config._before_send(_event(contexts={"trace": trace}), {}) is None


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"logentry": {"formatted": "boom 4242"}}, ["log", "app", "boom #"]),
        ({"logentry": {"message": "boom 4242"}}, ["log", "app", "boom #"]),
        ({"logentry": {}, "message": "boom 4242"}, ["log", "app", "boom #"]),
        (
            {"logentry": {"message": "boom 4242"}, "tags": {"logger": "MCP_USE"}, "logger": "x"},
            ["log", "MCP_USE", "boom #"],
        ),
        (
            {"logentry": {"message": "boom 4242"}, "logger": "sentry.exporter"},
            ["log", "sentry.exporter", "boom #"],
        ),
    ],
)
def test_the_fingerprint_reads_every_fallback_in_order(
    event: dict[str, object], expected: list[str]
) -> None:
    """Each source is a fallback: logentry.formatted, then message, then the event's own."""
    result = sentry_config._before_send(_event(**event), {})

    assert result is not None
    assert result["fingerprint"] == expected


def test_a_very_long_message_is_capped_for_readability() -> None:
    result = sentry_config._before_send(_event(logentry={"message": "z" * 400}), {})

    assert result is not None
    assert len(result["fingerprint"][2]) == 160


def test_an_event_with_no_message_keeps_sentry_s_own_grouping() -> None:
    """A blank fingerprint would merge every message-less event into one issue."""
    result = sentry_config._before_send(_event(logentry={}), {})

    assert result is not None
    assert "fingerprint" not in result


def test_the_hint_reaches_the_llm_attempt_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def record(event: Event, hint: Hint) -> Event:
        seen["hint"] = hint
        return event

    monkeypatch.setattr(sentry_config, "_drop_llm_attempt_errors", record)
    hint: Hint = {"exc_info": (ValueError, ValueError("x"), None)}

    sentry_config._before_send(_event(), hint)

    assert seen["hint"] is hint


@pytest.mark.regression
async def test_an_error_without_user_kwargs_still_reaches_sentry_as_that_user(
    sentry_events: list[Event],
) -> None:
    """A log line binds only its own kwargs; the request's user rides the wide event."""
    async with log_context("test_operation"):
        log.set(user={"id": "67bdb4367c7dd1f0ea343216"})
        log.error("executor run failed")

    assert [event["user"] for event in sentry_events] == [{"id": "67bdb4367c7dd1f0ea343216"}]


def test_an_unvalidatable_event_still_reaches_sentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising before_send makes the SDK drop the event, so it ships ungrouped instead."""
    warning = MagicMock()
    monkeypatch.setattr(sentry_config.log, "warning", warning)

    event = sentry_config._before_send(_event(tags={"logger": 5}), {})

    assert event is not None
    assert "fingerprint" not in event
    warning.assert_called_once_with("sentry_event_shaping_failed", error_type="ValidationError")


def test_a_user_without_an_id_still_gets_one() -> None:
    """Sentry allows a user dict with only a username; the event's own id must join it."""
    event = sentry_config._before_send(
        _event(extra={"user": {"id": "67bdb4367c7dd1f0ea343216"}}, user={"username": "a"}),
        {},
    )

    assert event is not None
    assert event["user"] == {"username": "a", "id": "67bdb4367c7dd1f0ea343216"}


def test_an_existing_fingerprint_is_not_replaced() -> None:
    """Scope code may have grouped the event already; ours must not silently undo it."""
    event = sentry_config._before_send(
        _event(logentry={"message": "boom 4242"}, fingerprint=["mine"]), {}
    )

    assert event is not None
    assert event["fingerprint"] == ["mine"]


def test_a_user_that_already_has_an_id_is_left_alone() -> None:
    """The caller's attribution wins; ours only fills a gap."""
    event = sentry_config._before_send(
        _event(user={"id": "existing"}, extra={"user": {"id": "67bdb4367c7dd1f0ea343216"}}),
        {},
    )

    assert event is not None
    assert event["user"] == {"id": "existing"}


def test_a_trace_export_failure_never_reaches_sentry() -> None:
    """It says the collector is unreachable, not that a request failed; Loki keeps the line."""
    from shared.py.logging import OTEL_LOGGER_DISPLAY_NAME

    cap_msg, cap_exc, _scope = _run_sink(
        _record(
            message="Failed to export span batch code: 502, reason: <html>",
            logger_name=OTEL_LOGGER_DISPLAY_NAME,
        )
    )

    cap_msg.assert_not_called()
    cap_exc.assert_not_called()


def test_an_arq_job_failure_is_left_to_the_arq_integration() -> None:
    """ArqIntegration reports the job with its own trace; this line cannot be deduped."""
    cap_msg, cap_exc, _scope = _run_sink(_record(message="job failed", logger_name="ARQ"))

    cap_msg.assert_not_called()
    cap_exc.assert_not_called()
