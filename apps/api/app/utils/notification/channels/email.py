"""Email notification channel adapter.

Sends via the Resend HTTP API (no vendor SDK — a plain ``httpx`` POST keeps the
send fully async so it doesn't block the event loop alongside the other
channels' concurrent deliveries). Missing ``RESEND_API_KEY`` /
``EMAIL_UNSUBSCRIBE_SECRET`` is an ops precondition, not a feature flag: the
adapter skips with a structured log until both are configured.

Template selection keys off ``notification.metadata["kind"]``:
``briefing_daily`` / ``briefing_weekly`` render the corresponding briefing
template from ``notification.content.rich_content`` (the same
``BriefingPayload`` dict the OpenUI dashboard card renders — no re-invoking
the LLM to reformat). Anything else renders the plain-notification template
from ``content.title`` / ``content.body``.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.notifications import (
    CHANNEL_TYPE_EMAIL,
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.services.briefing.edition_email import is_edition_kind, render_edition_email
from app.utils.email_utils import normalize_email
from app.utils.notification.channels.base import ChannelAdapter
from app.utils.notification.email_templates import (
    render_daily_brief_email,
    render_plain_notification_email,
    render_weekly_digest_email,
)
from app.utils.notification.unsubscribe import (
    build_unsubscribe_headers,
    build_unsubscribe_url,
)
from shared.py.wide_events import log

RESEND_SEND_URL = "https://api.resend.com/emails"
_SEND_TIMEOUT_SECONDS = 10.0


class EmailChannelAdapter(ChannelAdapter):
    """Sends notification content to the user's email via Resend."""

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_EMAIL

    def can_handle(self, notification: NotificationRequest) -> bool:
        """Always claim the notification; ``deliver`` decides skip vs send
        (no configured ESP keys, no email on file)."""
        return True

    async def transform(self, notification: NotificationRequest) -> dict[str, Any]:
        return {
            "kind": notification.metadata.get("kind"),
            "payload": notification.content.rich_content,
            "title": notification.content.title,
            "body": notification.content.body,
        }

    async def deliver(self, content: dict[str, Any], user_id: str) -> ChannelDeliveryStatus:
        if not settings.RESEND_API_KEY or not settings.EMAIL_UNSUBSCRIBE_SECRET:
            log.info(f"{LogTag.NOTIFICATION} Email skipped: ESP not configured")
            return self._skipped("email: RESEND_API_KEY/EMAIL_UNSUBSCRIBE_SECRET not configured")

        user = await user_repository.get(user_id)
        email = normalize_email(user.email or "") if user else None
        if not email:
            return self._skipped("email: no email address on file")

        unsubscribe_url = build_unsubscribe_url(user_id)
        kind = content.get("kind")
        payload = content.get("payload") or {}

        # Briefings render as a print-quality edition image inlined in the email.
        # If that render fails, degrade to the plain HTML template rather than drop
        # the user's brief entirely — logged loudly, not swallowed.
        if is_edition_kind(kind) and payload:
            try:
                html = await render_edition_email(
                    payload, kind=kind, user_id=user_id, unsubscribe_url=unsubscribe_url
                )
                subject = payload.get("headline") or content.get("title") or "Your GAIA brief"
            except Exception as exc:
                log.warning(
                    f"{LogTag.NOTIFICATION} Edition render failed, using plain template",
                    user_id=user_id,
                    kind=kind,
                    error=str(exc),
                )
                subject, html = self._render(content, unsubscribe_url)
        else:
            subject, html = self._render(content, unsubscribe_url)

        try:
            async with httpx.AsyncClient(timeout=_SEND_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    RESEND_SEND_URL,
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                    json={
                        "from": settings.EMAIL_FROM,
                        "to": [email],
                        "subject": subject,
                        "html": html,
                        "headers": build_unsubscribe_headers(user_id),
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            log.error(
                f"{LogTag.NOTIFICATION} Email send failed",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            return self._error(f"email: send failed ({e})")

        return self._success()

    def _render(self, content: dict[str, Any], unsubscribe_url: str) -> tuple[str, str]:
        """Picks the template by ``kind`` and returns ``(subject, html)``."""
        kind = content.get("kind")
        payload = content.get("payload") or {}
        title = content.get("title") or "GAIA"

        if kind == NOTIFICATION_KIND_BRIEFING_DAILY:
            return payload.get("headline") or title, render_daily_brief_email(
                payload, unsubscribe_url
            )
        if kind == NOTIFICATION_KIND_BRIEFING_WEEKLY:
            return payload.get("headline") or title, render_weekly_digest_email(
                payload, unsubscribe_url
            )
        return title, render_plain_notification_email(
            title, content.get("body") or "", unsubscribe_url
        )
