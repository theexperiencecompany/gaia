"""Give a brief its id and link, render its edition around that link, then store it.

The edition's QR and barcodes encode the brief's link, so the brief is stored and its link
minted before the render: a link is minted only to a target that exists. Every brief that is
stored (the daily, the weekly, the dev seed) goes through store_brief.
"""

from dataclasses import dataclass

from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import (
    BriefingKind,
    BriefingModel,
    BriefingPayload,
    EditionRender,
)
from app.models.short_link_models import ShortLinkTargetType
from app.services.briefing.edition_email import render_edition_png
from app.services.briefing.edition_image import store_edition
from app.services.briefing.message import full_brief_url
from app.services.links.service import optional_short_link


@dataclass(frozen=True)
class StoredBrief:
    """A stored brief and the link its edition encodes; None for a quiet day's note."""

    briefing: BriefingModel
    link: str | None


async def store_brief(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload
) -> StoredBrief:
    """Store the brief, mint its link (whose target must exist), render and store the edition, then store it with both.

    A render failure raises, leaving the brief stored without its edition and undelivered.
    Without a heygaia.link (sharing is off, or minting failed, which logs an error) the link
    is the brief's page, which its owner can always open.
    """
    briefing_id = await briefing_repository.briefing_id_for(user_id, date, kind)
    await briefing_repository.upsert_briefing(
        user_id, date, kind, payload, briefing_id=briefing_id, edition=None
    )
    link = await optional_short_link(
        user_id, ShortLinkTargetType.BRIEFING, briefing_id
    ) or full_brief_url(briefing_id)
    payload.link = link
    rendered = await render_edition_png(payload)
    key = await store_edition(user_id, briefing_id, rendered.image)
    briefing = await briefing_repository.upsert_briefing(
        user_id,
        date,
        kind,
        payload,
        briefing_id=briefing_id,
        edition=EditionRender(
            key=key, fold=rendered.fold, paper=list(rendered.paper) if rendered.paper else None
        ),
    )
    return StoredBrief(briefing=briefing, link=link)


async def store_note(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload
) -> StoredBrief:
    """Store a quiet day's note: no edition is rendered and no link is minted."""
    briefing_id = await briefing_repository.briefing_id_for(user_id, date, kind)
    briefing = await briefing_repository.upsert_briefing(
        user_id, date, kind, payload, briefing_id=briefing_id, edition=None
    )
    return StoredBrief(briefing=briefing, link=None)
