"""A persisted daily or weekly brief: its edition image and the payload the brief page renders."""

from app.db.repositories.briefings import briefing_repository
from app.db.repositories.short_links import short_link_repository
from app.models.brief_payload_models import BriefingItem
from app.models.short_link_models import (
    LinkAccess,
    LinkSnapshot,
    LinkTarget,
    LinkViewerKind,
    PublicBriefing,
    PublicBriefingEvent,
    PublicBriefingItem,
    PublicBriefingPayload,
    PublicBriefingSection,
    RecordTarget,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.briefing.view import edition_image
from app.services.links.access import at_most
from app.services.links.spec import LinkTargetSpec, PreviewFacts
from app.services.links.urls import build_url

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


async def _item_link(owner_id: str, item: BriefingItem, cap: LinkAccess | None) -> str | None:
    """Return the link an item shows: a deliverable's live link, read now, and none wider than cap.

    A link to anything else (a news item's own address) is shown as written.
    """
    if item.todo_id is None or item.link is None:
        return item.link
    live = await short_link_repository.get_live_for_target(
        owner_id, RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id=item.todo_id)
    )
    if live is None or (cap is not None and not at_most(live.access, cap)):
        return None
    return build_url(live.slug)


async def _project(
    link: ShortLink, target: RecordTarget, viewer: LinkViewerKind
) -> PublicBriefing | None:
    """Project the brief; for anyone but its owner, no item link opens wider than the brief's own."""
    briefing = await briefing_repository.get(target.id, user_id=link.user_id)
    if briefing is None:
        return None
    cap = None if viewer is LinkViewerKind.OWNER else link.access
    payload = briefing.payload
    image = await edition_image(briefing)
    return PublicBriefing(
        target_type=ShortLinkTargetType.BRIEFING,
        kind=briefing.kind,
        edition_image_url=image.image_url if image is not None else None,
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
                        PublicBriefingItem(
                            text=item.text,
                            kind=item.kind,
                            link=await _item_link(link.user_id, item, cap),
                        )
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


async def _carries(owner_id: str, target: RecordTarget) -> list[LinkTarget]:
    """Return the deliverables the brief links, whose GAIA-attached links follow the brief's access."""
    briefing = await briefing_repository.get(target.id, user_id=owner_id)
    if briefing is None:
        return []
    return [
        RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id=item.todo_id)
        for section in briefing.payload.sections
        for item in section.items
        if item.todo_id is not None and item.link is not None
    ]


async def _preview(
    owner_id: str, target: RecordTarget, _snapshot: LinkSnapshot | None
) -> PreviewFacts | None:
    briefing = await briefing_repository.get(target.id, user_id=owner_id)
    if briefing is None:
        return None
    return PreviewFacts(
        title=briefing.payload.headline,
        image_url=preview_image_url(
            image.image_url if (image := await edition_image(briefing)) else None
        ),
    )


SPEC = LinkTargetSpec(
    type=ShortLinkTargetType.BRIEFING,
    target=RecordTarget,
    kind_line="A brief from GAIA, the proactive personal assistant.",
    project=_project,
    preview=_preview,
    carries=_carries,
)
