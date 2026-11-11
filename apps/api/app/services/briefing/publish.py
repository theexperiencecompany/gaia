"""Publish a voiced brief: draw its edition, store it, deliver it, persist the draws and report it.

Persistence precedes delivery so the dashboard never misses a brief that reached a channel.
"""

from dataclasses import dataclass

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
)
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import (
    BriefingKind,
    BriefingModel,
    BriefingPayload,
)
from app.models.user_models import UserDocument
from app.services.analytics_service import capture
from app.services.briefing.context import UserClock
from app.services.briefing.delivery import deliver_brief
from app.services.briefing.edition_draws import BagDraw, draw_stamp_or_artwork, persist_draws
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.postmarks import new_stamp
from app.services.briefing.store import store_brief
from app.utils.user_display import display_name
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingSent
from shared.py.wide_events import log


@dataclass(frozen=True)
class PoolCounts:
    """How much the brief's fact pool held, beside what the composition placed from it."""

    items: int
    series: int

    @classmethod
    def of(cls, pool: FactPool) -> "PoolCounts":
        return cls(items=len(pool.items), series=len(pool.series))


@dataclass(frozen=True)
class Push:
    """Whether a brief goes beyond in-app, how many app signals it carried, and what its pool held."""

    push: bool
    pool: PoolCounts
    signal_count: int = 0


_NOTIFICATION_KINDS: dict[BriefingKind, str] = {
    BRIEFING_KIND_DAILY: NOTIFICATION_KIND_BRIEFING_DAILY,
    BRIEFING_KIND_WEEKLY: NOTIFICATION_KIND_BRIEFING_WEEKLY,
}


async def publish_brief(
    user: UserDocument,
    clock: UserClock,
    kind: BriefingKind,
    payload: BriefingPayload,
    draws: list[BagDraw],
    sending: Push,
) -> BriefingModel:
    """Draw the stamp or painting, render and store the brief, deliver it and report where it went.

    store_brief mints the link the edition encodes, then renders and stores it, so a
    render failure stores and sends nothing; the one image serves the in-app page, the email and the chat post. A brief
    that is not pushed (sending.push False) goes in-app only and spends no shuffle-bag draw;
    otherwise the draws (the family's and the stamp's or painting's) persist after delivery.
    """
    push = sending.push
    spent = [*draws, *draw_stamp_or_artwork(user, payload)]
    if payload.stamp_city is not None:
        payload.new_stamp = await new_stamp(user.id, payload.stamp_city)
    payload.recipient_name = display_name(user)
    stored = await store_brief(user.id, clock.date_str, kind, payload)
    channels = await deliver_brief(user, stored, payload, _NOTIFICATION_KINDS[kind], push=push)
    await briefing_repository.set_delivered_channels(user.id, clock.date_str, kind, channels)
    if push:
        await persist_draws(user.id, spent)
    capture(
        UserId(user.id),
        BriefingSent(
            kind=kind,
            family=payload.template_family,
            mood=payload.mood,
            item_count=sum(len(s.items) for s in payload.sections),
            channel_count=len(channels),
            signal_count=sending.signal_count,
            stamp_collected=payload.new_stamp is not None,
            block_kinds=[block.kind for block in payload.blocks],
            chart_count=sum(1 for block in payload.blocks if block.kind == "chart"),
            pool_item_count=sending.pool.items,
            series_count=sending.pool.series,
            source_count=len(payload.sources_read),
        ),
    )
    log.info("briefing.sent", user_id=user.id, kind=kind, channels=channels, pushed=push)
    return stored.briefing
