"""Sentry configuration for error tracking and performance monitoring."""

from collections.abc import Callable, Mapping
from typing import Protocol, TypedDict, cast

from loguru import logger as _loguru
import sentry_sdk

from app.config.loggers import REQUEST_LOGGER_NAME
from app.config.settings import settings
from app.constants.log_tags import LogTag
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


def _scrub_pii(extra: Mapping[str, object]) -> dict[str, object]:
    """Drop direct identifiers from wide-event fields, including nested dicts (user.email)."""
    return {
        key: _scrub_pii(value) if isinstance(value, dict) else value
        for key, value in extra.items()
        if key not in _PII_KEYS
    }


def _make_sentry_loguru_sink() -> Callable[[object], None]:
    """Return a Loguru sink that forwards ERROR+ records to Sentry.

    Bridges the gap left by Sentry's built-in LoggingIntegration, which only
    sees stdlib logging and never Loguru's error()/critical()/exception().
    """

    def _sink(message: object) -> None:
        # loguru hands the sink a Message whose .record is a stub-only TypedDict;
        # cast to the local shape so the field reads are key-checked.
        record: _Record = cast("_Message", message).record
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
        traces_sample_rate=0.1 if settings.ENV == "production" else 1.0,
        profiles_sample_rate=0.1 if settings.ENV == "production" else 1.0,
        # Loguru errors are captured separately via the sink below.
        enable_logs=True,
        profile_lifecycle="trace",
    )

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
