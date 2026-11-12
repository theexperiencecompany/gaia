"""A persisted daily or weekly brief: its edition image and the payload the brief page renders."""

from app.db.repositories.briefings import briefing_repository
from app.models.short_link_models import (
    LinkSnapshot,
    PublicBriefing,
    PublicBriefingEvent,
    PublicBriefingItem,
    PublicBriefingPayload,
    PublicBriefingSection,
    ShortLinkTargetType,
)
from app.services.links.spec import LinkTargetSpec, PreviewFacts

_CLOUDINARY_UPLOAD = "/image/upload/"
# The edition's top (masthead and headline) as a 1200x630 JPEG, the size chat previews show.
_OG_TRANSFORM = "c_fill,g_north,w_1200,h_630,f_jpg,q_auto/"


def preview_image_url(edition_image_url: str | None) -> str | None:
    """Return the edition image cropped for a chat preview; None when it is not on Cloudinary.

    Elsewhere (a self-host blob) the image needs a session, so the preview card is generated.
    """
    if edition_image_url is None or _CLOUDINARY_UPLOAD not in edition_image_url:
        return None
    head, _, tail = edition_image_url.partition(_CLOUDINARY_UPLOAD)
    return f"{head}{_CLOUDINARY_UPLOAD}{_OG_TRANSFORM}{tail}"


async def _project(
    owner_id: str, target_id: str, _snapshot: LinkSnapshot | None
) -> PublicBriefing | None:
    briefing = await briefing_repository.get(target_id, user_id=owner_id)
    if briefing is None:
        return None
    payload = briefing.payload
    return PublicBriefing(
        target_type=ShortLinkTargetType.BRIEFING,
        kind=briefing.kind,
        edition_image_url=briefing.edition_image_url,
        payload=PublicBriefingPayload(
            kicker=payload.kicker,
            date=payload.date,
            headline=payload.headline,
            lede=payload.lede,
            stats=payload.stats,
            sections=[
                PublicBriefingSection(
                    numeral=section.numeral,
                    title=section.title,
                    items=[
                        PublicBriefingItem(text=item.text, kind=item.kind, link=item.link)
                        for item in section.items
                    ],
                )
                for section in payload.sections
            ],
            mood=payload.mood,
            caption=payload.caption,
            hue=payload.hue,
            calendar=[
                PublicBriefingEvent(date=event.date, start=event.start, title=event.title)
                for event in payload.calendar
            ],
        ),
    )


async def _preview(
    owner_id: str, target_id: str, _snapshot: LinkSnapshot | None
) -> PreviewFacts | None:
    briefing = await briefing_repository.get(target_id, user_id=owner_id)
    if briefing is None:
        return None
    return PreviewFacts(
        title=briefing.payload.headline, image_url=preview_image_url(briefing.edition_image_url)
    )


SPEC = LinkTargetSpec(
    type=ShortLinkTargetType.BRIEFING,
    kind_line="A brief from GAIA, the proactive personal assistant.",
    project=_project,
    preview=_preview,
)
