"""Email notification channel adapter.

Sends through the platform email service (app/services/email). Missing
RESEND_API_KEY / EMAIL_UNSUBSCRIBE_SECRET is an ops precondition: the adapter skips
with a structured log. A failed send raises and the orchestrator records the channel
as failed.

Template selection keys off notification.metadata["kind"]: briefing_daily and
briefing_weekly render the briefing edition from content.rich_content, falling back
to the HTML briefing template if the edition render fails. Anything else renders the
plain-notification template.
"""

from __future__ import annotations

from typing import Any

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
    NotificationChannel,
)
from app.db.repositories.users import user_repository
from app.models.briefing_models import BriefingPayload
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.services.briefing.edition_email import is_edition_kind, render_edition_email
from app.services.briefing.skim import build_skim, full_brief_url
from app.services.email.models import EmailMessage
from app.services.email.service import send_email
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


class EmailChannelAdapter(ChannelAdapter):
    """Sends notification content to the user's email address."""

    @property
    def channel_type(self) -> str:
        return NotificationChannel.EMAIL

    def can_handle(self, notification: NotificationRequest) -> bool:
        """Claim every notification.

        deliver decides skip vs send.
        """
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
            skim = build_skim(BriefingPayload.model_validate(payload), full_brief_url())
            try:
                html = await render_edition_email(
                    payload,
                    kind=kind,
                    user_id=user_id,
                    unsubscribe_url=unsubscribe_url,
                    preheader=skim.preheader,
                )
                subject = skim.headline or content.get("title") or "Your GAIA brief"
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

        await send_email(
            EmailMessage(
                sender=settings.EMAIL_FROM,
                to=[email],
                subject=subject,
                html=html,
                headers=build_unsubscribe_headers(user_id),
            )
        )
        return self._success()

    def _render(self, content: dict[str, Any], unsubscribe_url: str) -> tuple[str, str]:
        """Pick the template by kind and return (subject, html)."""
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
