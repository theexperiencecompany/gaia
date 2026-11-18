"""A brief notification's email: the stored brief's edition image, linked to its heygaia.link, above its message.

The edition was rendered and hosted when the brief was stored; the email embeds the card's signed
edition URL. A notification whose card has no edition, or whose brief is no longer stored, cannot be
rendered and fails at transform. A quiet note declares no renderer, so it goes out as a plain email.
"""

from dataclasses import dataclass

from app.constants.notifications import NotificationKind
from app.db.repositories.briefings import briefing_repository
from app.models.brief_payload_models import BriefingPayload
from app.models.brief_view_models import BriefEditionNotification
from app.models.notification.notification_models import NotificationRequest
from app.services.briefing.edition_email import render_edition_email
from app.utils.notification.channels.email import EmailRenderer

_EDITION_DEFAULT_SUBJECT = "Your GAIA brief"


@dataclass(frozen=True)
class EditionEmail:
    """A daily brief's or weekly recap's email: its stored payload, heygaia.link and hosted edition image."""

    payload: BriefingPayload
    brief_url: str
    edition_image_url: str
    #: The notification's title, the subject when the brief has no headline.
    title: str

    def render(self, unsubscribe_url: str) -> tuple[str, str]:
        html = render_edition_email(
            self.payload,
            image_url=self.edition_image_url,
            brief_url=self.brief_url,
            unsubscribe_url=unsubscribe_url,
        )
        return self.payload.headline or self.title or _EDITION_DEFAULT_SUBJECT, html


async def edition_email(notification: NotificationRequest) -> EditionEmail:
    """Read the stored brief the notification's card names, with the card's edition and link."""
    metadata = BriefEditionNotification.model_validate(notification.metadata)
    card = metadata.card
    if card.edition is None:
        raise ValueError(f"a {metadata.kind} notification's card carries no edition")
    brief = await briefing_repository.get(card.briefing_id, user_id=notification.user_id)
    if brief is None:
        raise LookupError(
            f"brief {card.briefing_id} of a {metadata.kind} notification is not stored"
        )
    return EditionEmail(
        payload=brief.payload,
        brief_url=metadata.brief_url,
        edition_image_url=card.edition.image_url,
        title=notification.content.title,
    )


BRIEFING_EMAIL_RENDERERS: dict[NotificationKind, EmailRenderer] = {
    NotificationKind.BRIEFING_DAILY: edition_email,
    NotificationKind.BRIEFING_WEEKLY: edition_email,
}
