"""Slack side of delivery-failure alerting.

One parent message per incident, kept current with chat.update, and the first
occurrences posted in its thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel
from slack_sdk.http_retry.builtin_async_handlers import (
    AsyncConnectionErrorRetryHandler,
    AsyncRateLimitErrorRetryHandler,
    AsyncServerErrorRetryHandler,
)
from slack_sdk.web.async_client import AsyncWebClient

from app.config.settings import settings
from app.constants.chat import ConversationSource
from app.constants.delivery_alerts import (
    DELIVERY_FAILURE_KIND_LABELS,
    DELIVERY_INCIDENT_THREAD_LIMIT,
)
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts.incidents import Incident


@dataclass(frozen=True)
class AlertRecipient:
    """Who a failed message was for, as far as GAIA knows."""

    user_id: str | None
    email: str | None


class _PostedMessage(BaseModel):
    """The part of Slack's chat.postMessage response threading needs."""

    ts: str


def _escape(text: str) -> str:
    """Slack treats &, < and > as control characters in message text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _slack_time(moment: datetime, date_format: str = "{time}") -> str:
    """Format a timestamp each reader sees in their own timezone."""
    fallback = moment.isoformat(timespec="seconds")
    return f"<!date^{int(moment.timestamp())}^{date_format}|{fallback}>"


def render_incident(incident: Incident) -> str:
    """Render the parent message: what broke, how often, for how many people."""
    platform = ConversationSource(incident.platform).display_name
    label = DELIVERY_FAILURE_KIND_LABELS[incident.kind]
    cause = f"`{_escape(incident.error_code or incident.reason)}`"
    if incident.error_message:
        cause = f"{cause} {_escape(incident.error_message)}"

    noun = "failure" if incident.count == 1 else "failures"
    people = "1 recipient" if incident.users == 1 else f"{incident.users} recipients"
    stats = [f"*{incident.count} {noun}*", people]
    if incident.countries:
        stats.append(", ".join(incident.countries))
    stats.append(f"first {_slack_time(incident.first_at, '{date_short_pretty} {time}')}")
    stats.append(f"last {_slack_time(incident.last_at)}")

    lines = [f":rotating_light: *{platform}: {label}*", cause, " · ".join(stats)]
    if incident.count > DELIVERY_INCIDENT_THREAD_LIMIT:
        lines.append(f"_First {DELIVERY_INCIDENT_THREAD_LIMIT} shown in thread._")
    return "\n".join(lines)


def render_occurrence(failure: DeliveryFailure, recipient: AlertRecipient) -> str:
    """One thread reply: when, to whom, and the ids that find it in Loki and the platform."""
    if recipient.user_id:
        who = f"user `{recipient.user_id}`"
        if recipient.email:
            who = f"{who} {_escape(recipient.email)}"
    elif failure.is_channel:
        who = "a group channel"
    else:
        who = "an unlinked recipient"

    parts = [_slack_time(failure.occurred_at, "{time_secs}"), who]
    if failure.country:
        parts.append(failure.country)
    if failure.envelope_id:
        parts.append(f"envelope `{_escape(failure.envelope_id)}`")
    if failure.platform_message_id:
        parts.append(f"message `{_escape(failure.platform_message_id)}`")
    parts.append(f"via {_escape(failure.reporter)}")
    return " · ".join(parts)


class DeliveryAlertsSlack:
    """Posts and updates incident messages in the delivery-alerts channel."""

    def __init__(self, client: AsyncWebClient, channel_id: str) -> None:
        self._client = client
        self._channel_id = channel_id

    async def post_incident(self, incident: Incident) -> str:
        """Post the incident's parent message; returns its ts."""
        response = await self._client.chat_postMessage(
            channel=self._channel_id, text=render_incident(incident), unfurl_links=False
        )
        return _PostedMessage.model_validate(response.data).ts

    async def update_incident(self, incident: Incident, ts: str) -> None:
        """Re-render the parent message with the incident's current numbers."""
        await self._client.chat_update(
            channel=self._channel_id, ts=ts, text=render_incident(incident)
        )

    async def post_occurrence(
        self, ts: str, failure: DeliveryFailure, recipient: AlertRecipient
    ) -> None:
        """Reply in the incident's thread with one failure's details."""
        await self._client.chat_postMessage(
            channel=self._channel_id,
            thread_ts=ts,
            text=render_occurrence(failure, recipient),
            unfurl_links=False,
        )


@lazy_provider(
    name="delivery_alerts_slack",
    required_keys=[
        settings.SLACK_DELIVERY_ALERTS_BOT_TOKEN,
        settings.SLACK_DELIVERY_ALERTS_CHANNEL_ID,
    ],
    strategy=MissingKeyStrategy.WARN,
    warning_message="Slack delivery alerts not configured. Delivery failures will be logged but not posted.",
)
def init_delivery_alerts_slack() -> DeliveryAlertsSlack:
    """Build the Slack client for delivery alerts, retrying rate limits and transient errors."""
    client = AsyncWebClient(
        token=settings.SLACK_DELIVERY_ALERTS_BOT_TOKEN,
        retry_handlers=[
            AsyncConnectionErrorRetryHandler(),
            AsyncRateLimitErrorRetryHandler(max_retry_count=3),
            AsyncServerErrorRetryHandler(),
        ],
    )
    return DeliveryAlertsSlack(client, str(settings.SLACK_DELIVERY_ALERTS_CHANNEL_ID))


async def get_delivery_alerts_slack() -> DeliveryAlertsSlack | None:
    """Return the configured Slack poster, or None when delivery alerts are not configured."""
    slack: DeliveryAlertsSlack | None = await providers.aget("delivery_alerts_slack")
    return slack
