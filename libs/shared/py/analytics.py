"""Env-configured PostHog client for Python services outside the API.

The API builds its own client through its lazy-provider registry
(``apps/api/app/config/posthog.py``) because that is how every external client
in that app is wired. Services without that registry — the voice agent today —
need the same client without importing the API, and copying the construction
into each app is exactly the drift this package exists to prevent.

Event names follow the project-wide ``domain:action`` convention shared with
``apps/api/app/services/analytics_service.py`` and
``libs/shared/ts/src/analytics``.

Identity: ``distinct_id`` is always GAIA's stable user id. Never an email, never
a platform handle — those produce a second, unmergeable profile for the same
person.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import os
from typing import Any

from posthog import Posthog

from shared.py.wide_events import log

DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"


class VoiceAnalyticsEvents(StrEnum):
    """Voice-agent event names."""

    SESSION_STARTED = "voice:session_started"
    SESSION_ENDED = "voice:session_ended"


class PostHogAnalytics:
    """A PostHog client that no-ops when the project token is absent.

    Token-less environments (local dev without Infisical, CI) are legitimate, so
    a missing token disables capture instead of failing the process — the same
    contract as the API's SILENT provider strategy and the bots' `Analytics`.
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

    def capture(
        self,
        distinct_id: str,
        event: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Capture ``event`` for ``distinct_id`` (GAIA's stable user id)."""
        if self._client is None:
            return
        try:
            self._client.capture(
                event=event,
                distinct_id=distinct_id,
                properties={
                    **(properties or {}),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as e:
            # Analytics must never take down the caller, but the failure is a
            # real gap in the data — surface it rather than swallowing it.
            log.error(
                "Failed to capture event in PostHog",
                event=event,
                error=str(e),
                error_type=type(e).__name__,
            )

    def shutdown(self) -> None:
        """Flush queued events and close the client.

        ``shutdown()`` rather than ``flush()``: it also joins the consumer
        threads and stops the poller, which a short-lived worker process needs
        before the interpreter exits or the queued events are dropped.
        """
        if self._client is None:
            return
        self._client.shutdown()
