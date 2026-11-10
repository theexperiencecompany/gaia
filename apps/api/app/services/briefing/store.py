"""Give a brief its id and link, render its edition around that link, then store it.

The edition's QR and barcodes encode the brief's link, so the id and the link exist
before the render. Every brief that is stored (the daily, the weekly, the dev seed)
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
from app.models.short_link_models import ShortLinkTargetType
from app.services.briefing.edition_email import HostedEditionImage, host_edition_image
from app.services.briefing.message import full_brief_url
from app.services.short_link_service import optional_short_link


@dataclass(frozen=True)
class StoredBrief:
    """A stored brief, its hosted edition and the link that edition encodes."""

    briefing: BriefingModel
    image: HostedEditionImage
    link: str


async def store_brief(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload
) -> StoredBrief:
    """Mint the brief's link, set it on the payload, render and host the edition, then upsert.

    A render failure stores nothing. Without a heygaia.link (mint failed or sharing is
    off) the link is the brief's page, which its owner can always open.
    """
    briefing_id = await briefing_repository.briefing_id_for(user_id, date, kind)
    link = await optional_short_link(
        user_id, ShortLinkTargetType.BRIEFING, briefing_id
    ) or full_brief_url(briefing_id)
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
