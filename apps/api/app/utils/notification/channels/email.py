"""Email notification channel adapter.

Sends through the platform email service (app/services/email). Missing
RESEND_API_KEY / EMAIL_UNSUBSCRIBE_SECRET is an ops precondition: the adapter skips
with a structured log. A failed send raises and the orchestrator records the channel
as failed.

Template selection keys off notification.metadata["kind"]: briefing_daily and
briefing_weekly embed the edition image the briefing service already rendered and
hosted (metadata["edition_image_url"]), linked to the brief's heygaia.link
(metadata["brief_url"]). A briefing notification missing either, or its
content.rich_content payload, fails at transform. Anything else renders the
plain-notification template.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.notifications import NotificationChannel
from app.db.repositories.users import user_repository
from app.models.briefing_models import BriefingPayload
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.services.briefing.edition_email import is_edition_kind, render_edition_email
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
_EDITION_DEFAULT_SUBJECT = "Your GAIA brief"


class _EmailMetadata(BaseModel):
    """The notification-metadata field every email reads: the template kind."""

    kind: str | None = None


class _BriefingEmailMetadata(_EmailMetadata):
    """A briefing's metadata: its heygaia.link and its already-hosted edition image."""

    brief_url: str
    edition_image_url: str


@dataclass(frozen=True)
class BriefingEmail:
    """A daily or weekly briefing kind with its payload, heygaia.link and hosted edition image."""

    kind: str
    payload: BriefingPayload
    brief_url: str
    edition_image_url: str


@dataclass(frozen=True)
class EmailContent:
    """What one email is rendered from.

    briefing is set only for a briefing kind that carries its payload; everything
    else renders the plain-notification template from title and body.
    """

    title: str
    body: str
    briefing: BriefingEmail | None = None


class EmailChannelAdapter(ChannelAdapter[EmailContent]):
    """Sends notification content to the user's email address."""

    @property
    def channel_type(self) -> str:
        return NotificationChannel.EMAIL

    def can_handle(self, notification: NotificationRequest) -> bool:
        """Claim every notification.

        deliver decides skip vs send.
        """
        return True

    async def transform(self, notification: NotificationRequest) -> EmailContent:
        content = notification.content
        kind = _EmailMetadata.model_validate(notification.metadata).kind
        if kind is None or not is_edition_kind(kind):
            return EmailContent(title=content.title, body=content.body)

        metadata = _BriefingEmailMetadata.model_validate(notification.metadata)
        return EmailContent(
            title=content.title,
            body=content.body,
            briefing=BriefingEmail(
                kind=kind,
                payload=BriefingPayload.model_validate(content.rich_content),
                brief_url=metadata.brief_url,
                edition_image_url=metadata.edition_image_url,
            ),
        )

    async def deliver(self, content: EmailContent, user_id: str) -> ChannelDeliveryStatus:
        if not settings.RESEND_API_KEY or not settings.EMAIL_UNSUBSCRIBE_SECRET:
            log.info(f"{LogTag.NOTIFICATION} Email skipped: ESP not configured")
            return self._skipped("email: RESEND_API_KEY/EMAIL_UNSUBSCRIBE_SECRET not configured")

        user = await user_repository.get(user_id)
        email = normalize_email(user.email or "") if user else None
        if not email:
            return self._skipped("email: no email address on file")

        unsubscribe_url = build_unsubscribe_url(user_id)
        if content.briefing is None:
            subject = content.title or _DEFAULT_SUBJECT
            html = render_plain_notification_email(subject, content.body, unsubscribe_url)
        else:
            subject, html = _render_briefing(content.briefing, content.title, unsubscribe_url)

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


def _render_briefing(briefing: BriefingEmail, title: str, unsubscribe_url: str) -> tuple[str, str]:
    """Return (subject, html) for a briefing: the headline over its edition image and message."""
    html = render_edition_email(
        briefing.payload,
        image_url=briefing.edition_image_url,
        brief_url=briefing.brief_url,
        unsubscribe_url=unsubscribe_url,
    )
    return briefing.payload.headline or title or _EDITION_DEFAULT_SUBJECT, html
