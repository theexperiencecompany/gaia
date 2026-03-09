"""
Sentry configuration for error tracking and performance monitoring.
"""

from loguru import logger as _loguru
import sentry_sdk

from shared.py.wide_events import log
from app.config.settings import settings


def _make_sentry_loguru_sink():
    """Return a Loguru sink that forwards ERROR+ records to Sentry.

    Loguru does not emit through Python's stdlib logging, so Sentry's
    built-in LoggingIntegration / enable_logs=True never sees Loguru
    error() / critical() / exception() calls. This sink bridges that gap.

    Exceptions in the record are captured via capture_exception so that
    Sentry shows the full traceback. Plain error messages without an
    attached exception are forwarded as capture_message with level=error.
    """

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[attr-defined]
        if record["level"].no < 40:  # below ERROR — skip
            return

        extra = dict(record["extra"])
        exc_info = record["exception"]

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("logger", extra.get("logger_name", "app"))
            scope.set_tag("module", record["module"])
            for key, value in extra.items():
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


def init_sentry():
    """Initialize Sentry error tracking if DSN is configured."""

    if not settings.SENTRY_DSN:
        log.info("SENTRY_DSN is not configured, skipping Sentry initialization.")
        return

    log.info("SENTRY_DSN is configured, initializing Sentry.")
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=0.1 if settings.ENV == "production" else 1.0,
        # Set profile_session_sample_rate to 1.0 to profile 100%
        # of profile sessions.
        profiles_sample_rate=0.1 if settings.ENV == "production" else 1.0,
        # enable_logs captures stdlib logging records via Sentry's logging
        # integration. Loguru errors are captured separately via the sink below.
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
