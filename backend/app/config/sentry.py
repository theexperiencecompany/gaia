"""
Sentry configuration for error tracking and performance monitoring.
"""

from app.config.loggers import app_logger as logger
import sentry_sdk

from app.config.settings import settings


def init_sentry():
    """Initialize Sentry error tracking if DSN is configured."""

    if not settings.SENTRY_DSN:
        logger.info("SENTRY_DSN is not configured, skipping Sentry initialization.")
        return

    logger.info("SENTRY_DSN is configured, initializing Sentry.")
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
        # Set profile_lifecycle to "trace" to automatically
        # run the profiler on when there is an active transaction
        profile_lifecycle="trace",
    )
