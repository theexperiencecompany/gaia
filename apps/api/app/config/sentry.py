"""Sentry configuration for error tracking and performance monitoring."""

from collections.abc import Callable, Mapping
from typing import Protocol, TypedDict, cast

from loguru import logger as _loguru
from pydantic import BaseModel
import sentry_sdk
from sentry_sdk.consts import OP
from sentry_sdk.integrations.langchain import LangchainIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.types import Event, Hint

from app.config.deployment import DeploymentKind
from app.config.loggers import REQUEST_LOGGER_NAME
from app.config.settings import settings
from app.constants.log_tags import LogTag
from shared.py.logging import ARQ_LOGGER_DISPLAY_NAME, MCP_USE_LOGGER_DISPLAY_NAME, env_context
from shared.py.wide_events import (
    BOUNDARY_FAILURE_MESSAGE,
    BOUNDARY_LOGGER_NAMES,
    log,
)


class _Level(Protocol):
    no: int
    name: str


class _Exception(Protocol):
    value: BaseException | None


class _Extra(TypedDict, total=False):
    """The one wide-event field the sink routes on; the rest is scrubbed generically."""

    logger_name: str


class _Record(TypedDict):
    """The loguru record fields the Sentry sink reads (loguru's Record is stub-only)."""

    level: _Level
    extra: _Extra
    exception: _Exception | None
    module: str
    message: str


class _Message(Protocol):
    record: _Record


# Direct identifiers never leave the process for Sentry. Pseudonymous ids
# (user_id, trace_id, request_id) stay for correlation; join back to the
# full wide event in Loki via trace_id when the identifying detail is needed.
_PII_KEYS = frozenset({"client_ip", "email", "user_agent", "user_email"})

# ARQ logs a job failure from outside the job's context; ArqIntegration reports it
# itself, with the job's own trace, so the library's line cannot be deduped and is dropped.
_REPORTED_BY_CALLER_LOGGERS = frozenset({ARQ_LOGGER_DISPLAY_NAME})

# Connect attempts only: MCPClient.connect re-reports them with the integration id.
# The library's background session task has no caller in app/, so it stays.
_MCP_USE_CONNECT_DUPLICATES = (
    "OAuth initialization failed",
    "MCP protocol error during initialization",
    "Failed to connect to",
    "Both transport methods failed",
    "Error listing tools for connector",
)


def _scrub_pii(extra: Mapping[str, object]) -> dict[str, object]:
    """Drop direct identifiers from wide-event fields, including nested dicts (user.email)."""
    return {
        key: _scrub_pii(value) if isinstance(value, dict) else value
        for key, value in extra.items()
        if key not in _PII_KEYS
    }


# Spans LangchainIntegration opens around one model call (chat and completion models).
_LLM_CALL_SPAN_OPS = frozenset({OP.GEN_AI_CHAT, OP.GEN_AI_PIPELINE})


class _TraceContext(BaseModel):
    """The two fields of an event's trace context that name the span it was captured in."""

    origin: str | None = None
    op: str | None = None


class _EventContexts(BaseModel):
    trace: _TraceContext = _TraceContext()


class _CapturedSpan(BaseModel):
    """The part of a Sentry event that says which span captured it; other fields are ignored."""

    contexts: _EventContexts = _EventContexts()


def _drop_llm_attempt_errors(event: Event, _hint: Hint) -> Event | None:
    """Drop the error LangchainIntegration captures for every failed model call.

    Every model call runs through ainvoke_llm's retry and fallback policy, and its
    caller reports the failure only once the policy gives up; capturing each
    attempt turned upstream 429s into Sentry errors.
    """
    trace = _CapturedSpan.model_validate(event).contexts.trace
    if trace.origin == LangchainIntegration.origin and trace.op in _LLM_CALL_SPAN_OPS:
        return None
    return event


def _make_sentry_loguru_sink() -> Callable[[object], None]:
    """Return the Loguru sink that is the one path from a log record to a Sentry event.

    Sentry's own Loguru and logging integrations are disabled in init_sentry, so
    every record — app or library (stdlib reaches Loguru via the intercept
    handler) — passes this sink's filters and PII scrub exactly once.
    """

    def _sink(message: object) -> None:
        # loguru hands the sink a Message whose .record is a stub-only TypedDict;
        # cast to the local shape so the field reads are key-checked.
        record: _Record = cast(_Message, message).record
        if record["level"].no < 40:  # below ERROR — skip
            return

        extra: _Extra = record["extra"]
        logger_name = extra.get("logger_name")

        # Skip the per-request wide-event roll-up ("http_request"): forwarding it
        # would group every 5xx under one useless Sentry issue carrying PII in extras.
        if logger_name == REQUEST_LOGGER_NAME:
            return

        # Worker/background boundary roll-ups have a constant message, so every
        # task failure would collapse into one issue; the specific cause reaches
        # Sentry via its own log.error elsewhere.
        if logger_name in BOUNDARY_LOGGER_NAMES:
            return

        # The library's own line is logged outside the caller's context, so Sentry cannot dedupe it.
        if logger_name in _REPORTED_BY_CALLER_LOGGERS:
            return
        if logger_name == MCP_USE_LOGGER_DISPLAY_NAME and str(record["message"]).startswith(
            _MCP_USE_CONNECT_DUPLICATES
        ):
            return

        # The constant "task failed" line is skipped only when it carries no
        # exception; a boundary that raised without a specific error still
        # reaches Sentry below, captured as its attached exception.
        if record["message"] == BOUNDARY_FAILURE_MESSAGE and record["exception"] is None:
            return

        exc_info = record["exception"]

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("logger", logger_name or "app")
            scope.set_tag("module", record["module"])
            for key, value in _scrub_pii(cast("Mapping[str, object]", extra)).items():
                if key != "logger_name":
                    scope.set_extra(key, value)

            if exc_info is not None and exc_info.value is not None:
                sentry_sdk.capture_exception(exc_info.value)
            else:
                sentry_sdk.capture_message(
                    record["message"],
                    level="fatal" if record["level"].name == "CRITICAL" else "error",
                )

    return _sink


def init_sentry() -> None:
    """Initialize Sentry error tracking if DSN is configured."""

    if not settings.SENTRY_DSN:
        log.info(f"{LogTag.STARTUP} SENTRY_DSN is not configured, skipping Sentry initialization.")
        return

    log.info(f"{LogTag.STARTUP} SENTRY_DSN is configured, initializing Sentry.")
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        # Keep request headers, cookies and client IPs out of Sentry events —
        # the loguru sink already forwards the pseudonymous ids needed to
        # correlate an issue back to its wide event in Loki.
        send_default_pii=False,
        traces_sample_rate=0.1 if settings.deployment.kind is DeploymentKind.PRODUCTION else 1.0,
        profiles_sample_rate=0.1 if settings.deployment.kind is DeploymentKind.PRODUCTION else 1.0,
        profile_lifecycle="trace",
        # Both re-send every log record the sink below already forwards, unfiltered and unscrubbed.
        disabled_integrations=[LoguruIntegration(), LoggingIntegration()],
        before_send=_drop_llm_attempt_errors,
    )
    # The API and the ARQ worker share one project; the Promtail service name tells them apart.
    sentry_sdk.get_global_scope().set_tag("service", env_context().service)

    # Bridge Loguru → Sentry for ERROR and CRITICAL records.
    # Without this, log.error() / log.exception() calls are only visible
    # in Loki (via the wide event) and never reach Sentry.
    _loguru.add(
        _make_sentry_loguru_sink(),
        level="ERROR",
        # Don't enqueue — we want synchronous delivery so Sentry events
        # are captured before a worker task exits or a response is sent.
        enqueue=False,
        catch=True,  # never let a Sentry failure crash the app
    )
