"""Count every OAuth callback by flow and outcome, the signal the sign-in and connect alerts read.

login is a sign-in through WorkOS on any surface; integration is a Composio connection. failed is
a callback that redirected the user back with an error; cancelled is the user saying no on the
provider's consent screen, which is not a failure. Every series is created at zero when
the API starts, so the first failure after a restart is an increase.
"""

from enum import StrEnum

from prometheus_client import Counter

from app.utils.prometheus_registry import register_once


class OAuthFlow(StrEnum):
    """The kind of connection the callback completes."""

    LOGIN = "login"
    INTEGRATION = "integration"


class OAuthCallbackOutcome(StrEnum):
    """How one callback ended."""

    OK = "ok"
    FAILED = "failed"
    CANCELLED = "cancelled"


OAUTH_CALLBACK_TOTAL = register_once(
    "gaia_oauth_callback_total",
    lambda: Counter(
        name="gaia_oauth_callback_total",
        documentation="OAuth callbacks by flow and outcome; failed redirected the user back with an error",
        labelnames=("flow", "outcome"),
    ),
)


def observe_oauth_callback(flow: OAuthFlow, outcome: OAuthCallbackOutcome) -> None:
    """Count one OAuth callback by how it ended."""
    OAUTH_CALLBACK_TOTAL.labels(flow, outcome).inc()


def create_oauth_callback_series() -> None:
    """Create every OAuth callback series at zero, so its first increment is visible."""
    for flow in OAuthFlow:
        for outcome in OAuthCallbackOutcome:
            OAUTH_CALLBACK_TOTAL.labels(flow, outcome)
