"""Give a brief its id and link, render its edition around that link, then store it.

The edition's QR and barcodes encode the brief's link, so the brief is stored and its link
minted before the render: a link is minted only to a target that exists. Every brief that is
stored (the daily, the weekly, the dev seed) goes through store_brief.
"""

from app.constants.briefing import BriefingKind
from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import (
    BriefDelivery,
    BriefingModel,
    BriefingPayload,
    EditionRender,
)
from app.models.short_link_models import ShortLinkTargetType
from app.services.briefing.edition_email import render_edition_png
from app.services.briefing.edition_image import store_edition
from app.services.briefing.message import full_brief_url
from app.services.links.service import optional_short_link


async def _draft(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload, delivery: BriefDelivery
) -> BriefingModel:
    """Return the brief as it is stored, under the id its (user, date, kind) has or will have."""
    return BriefingModel(
        id=await briefing_repository.briefing_id_for(user_id, date, kind),
        user_id=user_id,
        date=date,
        kind=kind,
        payload=payload,
        delivery=delivery,
    )


async def store_brief(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload, delivery: BriefDelivery
) -> BriefingModel:
    """Store the brief, mint its link (whose target must exist), render and store the edition, then store it with both.

    A render failure raises, leaving the brief stored without its edition and undelivered.
    Without a heygaia.link (sharing is off, or minting failed, which logs an error) the link
    is the brief's page, which its owner can always open.
    """
    draft = await _draft(user_id, date, kind, payload, delivery)
    await briefing_repository.upsert_briefing(draft)
    payload.link = await optional_short_link(
        user_id, ShortLinkTargetType.BRIEFING, draft.id
    ) or full_brief_url(draft.id)
    rendered = await render_edition_png(payload)
    key = await store_edition(user_id, draft.id, rendered.image)
    edition = EditionRender(
        key=key, fold=rendered.fold, paper=list(rendered.paper) if rendered.paper else None
    )
    return await briefing_repository.upsert_briefing(
        draft.model_copy(update={"payload": payload, "edition": edition})
    )


async def store_note(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload, delivery: BriefDelivery
) -> BriefingModel:
    """Store a quiet day's note: no edition is rendered and no link is minted."""
    return await briefing_repository.upsert_briefing(
        await _draft(user_id, date, kind, payload, delivery)
    )
