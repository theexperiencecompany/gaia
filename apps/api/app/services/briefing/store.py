"""Give a brief its id and link, render its edition around that link, then store it.

The edition's QR and barcodes encode the brief's link, so the brief is stored and its link
minted before the render: a link is minted only to a target that exists. Every brief that is stored (the daily, the weekly, the dev seed)
goes through store_brief.
"""

from dataclasses import dataclass
from uuid import uuid4

from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import (
    BriefingKind,
    BriefingModel,
    BriefingPayload,
    EditionRender,
)
from app.models.short_link_models import RecordTarget, ShortLinkTargetType
from app.services.briefing.edition_email import HostedEditionImage, host_edition_image
from app.services.briefing.message import full_brief_url
from app.services.links.service import attach_link
from app.services.links.urls import build_url


@dataclass(frozen=True)
class StoredBrief:
    """A stored brief, its hosted edition and the link that edition encodes."""

    briefing: BriefingModel
    #: None for a quiet day's note, which has no edition and nothing to open.
    image: HostedEditionImage | None
    link: str | None


async def store_brief(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload
) -> StoredBrief:
    """Store the brief, mint its link (whose target must exist), render and host the edition, then store it with both.

    A render failure raises, leaving the brief stored without its edition and undelivered.
    Without a heygaia.link (sharing is off, or minting failed, which logs an error) the link
    is the brief's page, which its owner can always open.
    """
    briefing_id = await briefing_repository.briefing_id_for(user_id, date, kind)
    await briefing_repository.upsert_briefing(
        user_id, date, kind, payload, briefing_id=briefing_id, edition=None
    )
    short_link = await attach_link(
        user_id, RecordTarget(type=ShortLinkTargetType.BRIEFING, id=briefing_id)
    )
    link = build_url(short_link.slug) if short_link else full_brief_url(briefing_id)
    payload.link = link
    # A fresh random key per render: the hosted URL reaches emails and public links.
    image = await host_edition_image(payload, owner_id=user_id, render_key=uuid4().hex)
    briefing = await briefing_repository.upsert_briefing(
        user_id,
        date,
        kind,
        payload,
        briefing_id=briefing_id,
        edition=EditionRender(
            image_url=image.display_url,
            fold=image.fold,
            paper=list(image.paper) if image.paper else None,
        ),
    )
    return StoredBrief(briefing=briefing, image=image, link=link)


async def store_note(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload
) -> StoredBrief:
    """Store a quiet day's note: no edition is rendered and no link is minted."""
    briefing_id = await briefing_repository.briefing_id_for(user_id, date, kind)
    briefing = await briefing_repository.upsert_briefing(
        user_id, date, kind, payload, briefing_id=briefing_id, edition=None
    )
    return StoredBrief(briefing=briefing, image=None, link=None)
