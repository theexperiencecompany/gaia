"""Count Composio webhook outcomes: connection token refreshes and inbound trigger events.

A connection event reports whether the account's token refresh left it live or dead; a trigger
event is counted by whether its background processing finished. Both series are created at zero
when the API starts, so the first failure after a restart is an increase.
"""

from enum import StrEnum

from prometheus_client import Counter

from app.utils.prometheus_registry import register_once


class WebhookOutcome(StrEnum):
    """How one Composio webhook event ended."""

    OK = "ok"
    FAILED = "failed"


INTEGRATION_TOKEN_REFRESH_TOTAL = register_once(
    "gaia_integration_token_refresh_total",
    lambda: Counter(
        name="gaia_integration_token_refresh_total",
        documentation="Integration token refreshes by outcome; failed left the account dead",
        labelnames=("outcome",),
    ),
)

TRIGGER_WEBHOOK_TOTAL = register_once(
    "gaia_trigger_webhook_total",
    lambda: Counter(
        name="gaia_trigger_webhook_total",
        documentation="Inbound Composio trigger events by the outcome of their background processing",
        labelnames=("outcome",),
    ),
)


def create_composio_webhook_series() -> None:
    """Create every Composio webhook series at zero, so its first increment is visible."""
    for outcome in WebhookOutcome:
        INTEGRATION_TOKEN_REFRESH_TOTAL.labels(outcome)
        TRIGGER_WEBHOOK_TOTAL.labels(outcome)
