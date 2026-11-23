"""Email notification channel adapter.

Sends through the platform email service (app/services/email). Missing
RESEND_API_KEY / EMAIL_UNSUBSCRIBE_SECRET is an ops precondition: the adapter skips
with a structured log. A failed send raises and the orchestrator records the channel
as failed.

A notification whose details' kind has a renderer in the registry the adapter is built
with is rendered by it, and one that renderer cannot render fails at transform. Anything
else renders the plain-notification template.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.notifications import NotificationChannel, NotificationKind
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.services.email.models import EmailMessage
from app.services.email.service import send_email
from app.utils.email_utils import normalize_email
from app.utils.notification.channels.base import ChannelAdapter
from app.utils.notification.email_templates import render_plain_notification_email
from app.utils.notification.unsubscribe import (
    build_unsubscribe_headers,
    build_unsubscribe_url,
)
from shared.py.wide_events import log

_DEFAULT_SUBJECT = "GAIA"


class RenderableEmail(Protocol):
    """An email ready to send once its recipient's unsubscribe link is known."""

    def render(self, unsubscribe_url: str) -> tuple[str, str]:
        """Return the email's (subject, html)."""
        ...


#: Turns a notification of its kind into its email; raises when it cannot be rendered.
EmailRenderer = Callable[[NotificationRequest], Awaitable[RenderableEmail]]
EmailRenderers = Mapping[NotificationKind, EmailRenderer]


@dataclass(frozen=True)
class PlainEmail:
    """A notification's title and body in the plain-notification template."""

    title: str
    body: str

    def render(self, unsubscribe_url: str) -> tuple[str, str]:
        subject = self.title or _DEFAULT_SUBJECT
        return subject, render_plain_notification_email(subject, self.body, unsubscribe_url)


class EmailChannelAdapter(ChannelAdapter[RenderableEmail]):
    """Sends notification content to the user's email address."""

    def __init__(self, renderers: EmailRenderers) -> None:
        self._renderers = renderers

    @property
    def channel_type(self) -> str:
        return NotificationChannel.EMAIL

    def can_handle(self, notification: NotificationRequest) -> bool:
        """Claim every notification.

        deliver decides skip vs send.
        """
        return True

    async def transform(self, notification: NotificationRequest) -> RenderableEmail:
        details = notification.details
        renderer = self._renderers.get(details.kind) if details is not None else None
        if renderer is None:
            return PlainEmail(title=notification.content.title, body=notification.content.body)
        return await renderer(notification)

    async def deliver(self, content: RenderableEmail, user_id: str) -> ChannelDeliveryStatus:
        if not settings.RESEND_API_KEY or not settings.EMAIL_UNSUBSCRIBE_SECRET:
            log.info(f"{LogTag.NOTIFICATION} Email skipped: ESP not configured")
            return self._skipped("email: RESEND_API_KEY/EMAIL_UNSUBSCRIBE_SECRET not configured")

        user = await user_repository.get(user_id)
        email = normalize_email(user.email or "") if user else None
        if not email:
            return self._skipped("email: no email address on file")

        subject, html = content.render(build_unsubscribe_url(user_id))
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
