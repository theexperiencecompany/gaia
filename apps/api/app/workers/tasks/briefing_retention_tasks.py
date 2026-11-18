"""Nightly sweep that deletes briefs past their retention, each with its edition image.

A TTL index would drop the document and strand its image in the blob store, so retention
is this sweep's: the image goes first, then the brief that names it.
"""

from datetime import UTC, datetime

from app.constants.briefing import BRIEFING_EXPIRY_PAGE, BRIEFING_RETENTION
from app.constants.log_tags import LogTag
from app.db.repositories.briefings import briefing_repository
from app.services.briefing.edition_image import delete_edition
from app.workers.task_envelope import ArqJobContext
from shared.py.wide_events import log


async def sweep_expired_briefings(_ctx: ArqJobContext) -> str:
    """Delete every brief written more than BRIEFING_RETENTION ago, and its edition image."""
    cutoff = datetime.now(UTC) - BRIEFING_RETENTION
    briefs = images = 0
    while page := await briefing_repository.list_expired(cutoff, BRIEFING_EXPIRY_PAGE):
        for brief in page:
            if brief.edition_key is not None:
                await delete_edition(brief.user_id, brief.edition_key)
                images += 1
            await briefing_repository.delete(brief.id, user_id=brief.user_id)
            briefs += 1
    summary = {"briefs_expired": briefs, "edition_images_deleted": images}
    log.set(briefing_retention=summary)
    log.info(f"{LogTag.WORKER} expired briefs swept", **summary)
    return f"expired={briefs} images={images}"
