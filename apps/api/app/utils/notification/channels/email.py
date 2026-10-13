"""Email notification channel adapter.

Sends through the platform email service (``app/services/email``), the same
provider path every other GAIA email takes. Missing ``RESEND_API_KEY`` /
``EMAIL_UNSUBSCRIBE_SECRET`` is an ops precondition, not a feature flag: the
adapter skips with a structured log until both are configured. A send that
fails raises, and the orchestrator records the channel as failed.

Template selection keys off ``notification.metadata["kind"]``:
``briefing_daily`` / ``briefing_weekly`` render the briefing email from
``notification.content.rich_content`` (the same ``BriefingPayload`` dict the
dashboard card renders). Anything else renders the plain notification email
from ``content.title`` / ``content.body``.
"""

from __future__ import annotations

from typing import Any

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.notifications import NotificationChannel
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.services.email.models import EmailMessage
from app.services.email.service import send_email
from app.utils.email_utils import normalize_email
from app.utils.notification.channels.base import ChannelAdapter
from app.utils.notification.email_templates import (
    is_briefing_kind,
    render_briefing_email,
    render_notification_email,
)
from app.utils.notification.unsubscribe import (
    build_unsubscribe_headers,
    build_unsubscribe_url,
)
from shared.py.wide_events import log

_DEFAULT_SUBJECT = "GAIA"


class EmailChannelAdapter(ChannelAdapter):
    """Sends notification content to the user's email address."""

    @property
    def channel_type(self) -> str:
        return NotificationChannel.EMAIL

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

        subject, html = self._render(content, build_unsubscribe_url(user_id))
        await send_email(
            EmailMessage(
                sender=f"GAIA <{settings.EMAIL_FROM}>",
                to=[email],
                subject=subject,
                html=html,
                headers=build_unsubscribe_headers(user_id),
            )
        )
        return self._success()

    def _render(self, content: dict[str, Any], unsubscribe_url: str) -> tuple[str, str]:
        """Picks the template by ``kind`` and returns ``(subject, html)``."""
        kind = content.get("kind")
        if is_briefing_kind(kind):
            # A briefing without its payload is a producer bug: validation in
            # render_briefing_email fails the send rather than mailing a blank.
            return render_briefing_email(content.get("payload") or {}, kind, unsubscribe_url)
        title = content.get("title") or _DEFAULT_SUBJECT
        return title, render_notification_email(title, content.get("body") or "", unsubscribe_url)
