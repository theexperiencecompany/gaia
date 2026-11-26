"""A brief notification's email: the stored brief's edition image, linked to its heygaia.link, above its message.

The edition was rendered and hosted when the brief was stored; the email embeds a signed URL of
its compact encoding, a fraction of the lossless one's bytes. A notification whose brief is no
longer stored, or was stored without an edition, cannot be rendered and fails at transform. A
quiet note declares no renderer, so it goes out as a plain email.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.briefing import EditionVariant
from app.constants.notifications import NotificationKind
from app.db.repositories.briefings import briefing_repository
from app.models.brief_payload_models import BriefingPayload
from app.models.brief_view_models import BriefEditionNotification
from app.models.notification.notification_models import NotificationRequest
from app.services.briefing.edition_email import render_edition_email
from app.services.briefing.edition_image import edition_url
from app.utils.notification.channels.email import EmailRenderer

_EDITION_DEFAULT_SUBJECT = "Your GAIA brief"


@dataclass(frozen=True)
class EditionEmail:
    """A daily brief's or weekly recap's email: its stored payload, heygaia.link and hosted edition image."""

    payload: BriefingPayload
    brief_url: str
    edition_image_url: str
    subject: str

    def render(self, unsubscribe_url: str) -> tuple[str, str]:
        html = render_edition_email(
            self.payload,
            image_url=self.edition_image_url,
            brief_url=self.brief_url,
            unsubscribe_url=unsubscribe_url,
        )
        return self.subject or _EDITION_DEFAULT_SUBJECT, html


async def edition_email(notification: NotificationRequest) -> EditionEmail:
    """Read the stored brief the notification's card names, with its link and compact edition image."""
    details = notification.details
    if not isinstance(details, BriefEditionNotification):
        raise TypeError(f"an edition email needs a brief edition's details, not {details!r}")
    briefing_id = details.card.briefing_id
    brief = await briefing_repository.get(briefing_id, user_id=notification.user_id)
    if brief is None:
        raise LookupError(f"brief {briefing_id} of a {details.kind} notification is not stored")
    if brief.edition is None:
        raise ValueError(f"brief {briefing_id} of a {details.kind} notification has no edition")
    content = notification.content
    return EditionEmail(
        payload=brief.payload,
        brief_url=details.brief_url,
        edition_image_url=await edition_url(
            brief.edition.key, EditionVariant.JPG, datetime.now(UTC)
        ),
        subject=content.email_subject or content.title,
    )


BRIEFING_EMAIL_RENDERERS: dict[NotificationKind, EmailRenderer] = {
    NotificationKind.BRIEFING_DAILY: edition_email,
    NotificationKind.BRIEFING_WEEKLY: edition_email,
}
