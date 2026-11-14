"""Give every live file link minted before snapshots one, so resolution never reads a live file."""

from dataclasses import dataclass

from app.db.repositories.short_links import short_link_repository
from app.models.short_link_models import RevokeReason, ShortLinkUpdate
from app.services.links.content import publish
from app.services.links.registry import REGISTRY
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class BackfillReport:
    """What a run found (pending) and, applied, did: published a snapshot or marked the target deleted."""

    pending: int
    published: int
    target_deleted: int


async def backfill_snapshots(*, apply: bool) -> BackfillReport:
    """Snapshot every live link of a file type that has none; a dry run only counts them.

    Idempotent: a link with a snapshot is never touched again. A file that is
    gone revokes its link as target_deleted.
    """
    pending = published = deleted = 0
    for spec in REGISTRY.values():
        if spec.source is None:
            continue
        for link in await short_link_repository.live_without_snapshot(spec.type):
            pending += 1
            if not apply:
                continue
            source = await spec.source(link.user_id, link.target_id)
            if source is None:
                await short_link_repository.revoke(
                    link.user_id, link.slug, RevokeReason.TARGET_DELETED
                )
                deleted += 1
                continue
            snapshot = await publish(link.user_id, link.target_type, source)
            await short_link_repository.update(
                link.slug, user_id=link.user_id, update=ShortLinkUpdate(snapshot=snapshot)
            )
            published += 1
    log.info(
        "short_link.backfill",
        apply=apply,
        pending=pending,
        published=published,
        target_deleted=deleted,
    )
    return BackfillReport(pending=pending, published=published, target_deleted=deleted)
