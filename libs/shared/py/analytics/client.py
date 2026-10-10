"""The one way a Python service hands a catalog event to PostHog.

The API builds its own client through its lazy-provider registry
(apps/api/app/config/posthog.py); services without that registry, the voice
agent today, use PostHogAnalytics. Both build the payload with prepare_capture, so
the two cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from uuid import NAMESPACE_URL, uuid5

from posthog import Posthog

from shared.py.analytics.catalog.base import AnalyticsEvent, Surface, VoiceEvent
from shared.py.analytics.context import current_analytics_context
from shared.py.analytics.identity import AnalyticsId, PlatformIdentity, UserId
from shared.py.wide_events import log

DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"
#: Ingestion otherwise moves timestamp by (its clock - sent_at), so a resend lands at another time.
IGNORE_SENT_AT = "$ignore_sent_at"


@dataclass(frozen=True, slots=True)
class Dedupe:
    """The fact an event records: its key and when it happened, so every resend is one PostHog row.

    PostHog merges duplicates only when uuid, event, timestamp and distinct_id
    all match, so both the uuid and the timestamp come from here, never now().
    """

    key: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        """Refuse an empty key or a naive occurrence time."""
        if not self.key:
            raise ValueError("Dedupe needs a key")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Dedupe.occurred_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PostHogCapture:
    """One validated capture, ready to hand to a PostHog client."""

    event: str
    distinct_id: str
    properties: dict[str, object]
    uuid: str | None = None
    timestamp: datetime | None = None

    def send(self, client: Posthog) -> None:
        """Enqueue the capture on client."""
        client.capture(
            event=self.event,
            distinct_id=self.distinct_id,
            properties=self.properties,
            uuid=self.uuid,
            timestamp=self.timestamp,
        )


def check_capture(distinct_id: AnalyticsId, event: AnalyticsEvent, owner: Surface) -> None:
    """Refuse a capture whose id is not an AnalyticsId or whose event another surface owns."""
    if not isinstance(distinct_id, UserId | PlatformIdentity):
        raise TypeError(f"distinct_id must be a UserId or PlatformIdentity, got {distinct_id!r}")
    if not isinstance(event, AnalyticsEvent):
        raise TypeError(f"event must be a catalog event model, got {event!r}")
    if event.owner is not owner:
        raise TypeError(f"{event.event} is a {event.owner} event; {owner} may not emit it")


def prepare_capture(
    distinct_id: AnalyticsId, event: AnalyticsEvent, owner: Surface, dedupe: Dedupe | None = None
) -> PostHogCapture:
    """Validate a capture and stamp it with the bound analytics context and its dedupe identity.

    Raises MissingAnalyticsContextError for an attributed event captured where
    no entry point bound a context, and ValueError for an at-most-once event
    captured without the dedupe that keys its gate.
    """
    check_capture(distinct_id, event, owner)
    if event.at_most_once_ttl is not None and dedupe is None:
        raise ValueError(f"{event.event} fires at most once, so it needs a Dedupe")
    properties = event.to_properties()
    if event.base_properties is not None:
        properties |= current_analytics_context().to_properties()
    if dedupe is None:
        return PostHogCapture(event.event, distinct_id.distinct_id, properties)
    return PostHogCapture(
        event.event,
        distinct_id.distinct_id,
        properties | {IGNORE_SENT_AT: True},
        uuid=str(uuid5(NAMESPACE_URL, f"{event.event}:{distinct_id.distinct_id}:{dedupe.key}")),
        timestamp=dedupe.occurred_at,
    )


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
        capture = prepare_capture(distinct_id, event, Surface.VOICE)
        if self._client is None:
            return
        try:
            capture.send(self._client)
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
