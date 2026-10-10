"""The one way a Python service hands a catalog event to PostHog.

The API builds its own client through its lazy-provider registry
(apps/api/app/config/posthog.py); services without that registry, the voice
agent today, use PostHogAnalytics. Both validate through check_capture and
build the payload with posthog_properties, so the two cannot drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os

from posthog import Posthog

from shared.py.analytics.catalog.base import AnalyticsEvent, Surface, VoiceEvent
from shared.py.analytics.identity import AnalyticsId, PlatformIdentity, UserId
from shared.py.wide_events import log

DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"


def check_capture(distinct_id: AnalyticsId, event: AnalyticsEvent, owner: Surface) -> None:
    """Refuse a capture whose id is not an AnalyticsId or whose event another surface owns."""
    if not isinstance(distinct_id, UserId | PlatformIdentity):
        raise TypeError(f"distinct_id must be a UserId or PlatformIdentity, got {distinct_id!r}")
    if not isinstance(event, AnalyticsEvent):
        raise TypeError(f"event must be a catalog event model, got {event!r}")
    if event.owner is not owner:
        raise TypeError(f"{event.event} is a {event.owner} event; {owner} may not emit it")


def posthog_properties(event: AnalyticsEvent) -> dict[str, object]:
    """Build the property payload sent with an event."""
    return {**event.to_properties(), "timestamp": datetime.now(UTC).isoformat()}


class PostHogAnalytics:
    """A PostHog client that no-ops when the project token is absent.

    Token-less environments (local dev without Infisical, CI) are legitimate, so
    a missing token disables capture instead of failing the process, the same
    contract as the API's SILENT provider strategy and the bots' Analytics.
    """

    def __init__(self, project_token: str | None = None, host: str | None = None) -> None:
        token = (
            project_token if project_token is not None else os.environ.get("POSTHOG_PROJECT_TOKEN")
        )
        if not token:
            self._client: Posthog | None = None
            return
        resolved_host = host or os.environ.get("POSTHOG_HOST") or DEFAULT_POSTHOG_HOST
        self._client = Posthog(token, host=resolved_host)

    @property
    def enabled(self) -> bool:
        """Whether a client was configured; False means every capture no-ops."""
        return self._client is not None

    def capture(self, distinct_id: AnalyticsId, event: VoiceEvent) -> None:
        """Capture a voice-owned catalog event for distinct_id."""
        check_capture(distinct_id, event, Surface.VOICE)
        if self._client is None:
            return
        try:
            self._client.capture(
                event=event.event,
                distinct_id=distinct_id.distinct_id,
                properties=posthog_properties(event),
            )
        except Exception as e:
            # Analytics must never take down the caller, but the failure is a
            # real gap in the data, so surface it rather than swallowing it.
            log.error(
                "Failed to capture event in PostHog",
                event=event.event,
                error=str(e),
                error_type=type(e).__name__,
            )

    def shutdown(self) -> None:
        """Flush queued events and close the client.

        shutdown() rather than flush(): it also joins the consumer threads and
        stops the poller, which a short-lived worker process needs before the
        interpreter exits or the queued events are dropped.
        """
        if self._client is None:
            return
        self._client.shutdown()
