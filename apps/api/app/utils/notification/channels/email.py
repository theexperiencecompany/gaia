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

from dataclasses import dataclass

from pydantic import BaseModel

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.notifications import (
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

_DEFAULT_SUBJECT = "GAIA"
_EDITION_DEFAULT_SUBJECT = "Your GAIA brief"


class _EmailMetadata(BaseModel):
    """The one notification-metadata field this channel reads: the template kind."""

    kind: str | None = None


@dataclass(frozen=True)
class BriefingEmail:
    """A daily or weekly briefing kind with the payload it renders."""

    kind: str
    payload: BriefingPayload


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
        kind = _EmailMetadata.model_validate(notification.metadata).kind
        rich_content = notification.content.rich_content
        return EmailContent(
            title=notification.content.title,
            body=notification.content.body,
            briefing=(
                BriefingEmail(kind=kind, payload=BriefingPayload.model_validate(rich_content))
                if kind is not None and is_edition_kind(kind) and rich_content
                else None
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
            subject, html = await self._render_briefing(
                content.briefing, content.title, user_id, unsubscribe_url
            )

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

    async def _render_briefing(
        self, briefing: BriefingEmail, title: str, user_id: str, unsubscribe_url: str
    ) -> tuple[str, str]:
        """Render a briefing as a print-quality edition image inlined in the email.

        If that render fails, degrade to the HTML briefing template rather than drop
        the user's brief entirely — logged loudly, not swallowed. Returns (subject, html).
        """
        payload = briefing.payload
        skim = build_skim(payload, full_brief_url())
        try:
            html = await render_edition_email(
                payload,
                kind=briefing.kind,
                user_id=user_id,
                unsubscribe_url=unsubscribe_url,
                preheader=skim.preheader,
            )
        except Exception as exc:
            log.warning(
                f"{LogTag.NOTIFICATION} Edition render failed, using plain template",
                user_id=user_id,
                kind=briefing.kind,
                error=str(exc),
            )
            render_template = (
                render_weekly_digest_email
                if briefing.kind == NOTIFICATION_KIND_BRIEFING_WEEKLY
                else render_daily_brief_email
            )
            return payload.headline or title or _DEFAULT_SUBJECT, render_template(
                payload, unsubscribe_url
            )
        return skim.headline or title or _EDITION_DEFAULT_SUBJECT, html
