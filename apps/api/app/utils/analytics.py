"""Server-side product analytics (PostHog).

Retention/conversion events are emitted at state transitions on the server —
never from the client — so approve rate, activation, and quota conversion are
derived from one trustworthy source. No-ops silently when PostHog is not
configured (dev without keys), but never swallows unexpected errors from our
own call sites.
"""

from posthog import Posthog

from app.config.posthog import init_posthog
from shared.py.wide_events import log

_client: Posthog | None = None
_initialized = False


def _get_client() -> Posthog | None:
    global _client, _initialized
    if not _initialized:
        _client = init_posthog()
        _initialized = True
    return _client


def track(user_id: str, event: str, properties: dict | None = None) -> None:
    """Emit one analytics event for a user. Silent no-op when unconfigured."""
    client = _get_client()
    if client is None:
        return
    try:
        client.capture(distinct_id=user_id, event=event, properties=properties or {})
    except Exception as e:
        # Analytics must never break a product path; log so drops are visible.
        log.warning("analytics.capture_failed", event=event, error=str(e))
