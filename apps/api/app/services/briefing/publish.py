"""Publish a built brief: store it, deliver it, persist its draws and report where it went.

The payload arrives whole: an edition drawn, voiced and built, or a quiet note. Persistence
precedes delivery so the dashboard never misses a brief that reached a channel.
"""

from dataclasses import dataclass, field

from app.constants.briefing import BriefForm, BriefingKind
from app.constants.notifications import NOTIFICATION_KIND_BRIEFING_NOTE
from app.db.repositories.briefings import briefing_repository
from app.models.brief_composition_models import ChartBlock
from app.models.brief_document_models import BriefDelivery, BriefingModel
from app.models.brief_payload_models import BriefingPayload
from app.models.user_models import UserDocument
from app.services.analytics_service import capture
from app.services.briefing.clock import UserClock
from app.services.briefing.delivery import deliver_brief
from app.services.briefing.edition_draws import BagDraw, persist_draws
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.kinds import BriefKindSpec
from app.services.briefing.store import store_brief, store_note
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
class Sending:
    """Whether a brief goes beyond in-app, what it carried, what its pool held and what it drew."""

    push: bool
    pool: PoolCounts
    signal_count: int = 0
    #: The held results the brief accounts for, consumed once it is delivered.
    held_ids: list[str] = field(default_factory=list)
    #: The edition's bag draws, persisted once a pushed brief went out.
    draws: list[BagDraw] = field(default_factory=list)


async def publish(
    user: UserDocument,
    clock: UserClock,
    spec: BriefKindSpec,
    payload: BriefingPayload,
    sending: Sending,
) -> BriefingModel:
    """Store the brief, deliver it and report where it went; a pushed brief spends its draws.

    An edition is rendered around its link as it is stored, and a render failure stores and
    sends nothing; a quiet note renders no edition. A brief that is not pushed goes in-app
    only and spends no shuffle-bag draw.
    """
    note = payload.form is BriefForm.QUIET_NOTE
    plan = BriefDelivery(
        push=sending.push,
        notification_kind=NOTIFICATION_KIND_BRIEFING_NOTE if note else spec.notification_kind,
        held_ids=sending.held_ids,
    )
    store = store_note if note else store_brief
    stored = await store(user.id, clock.date_str, spec.kind, payload, plan)
    channels = await deliver_brief(user, stored)
    if sending.push:
        await persist_draws(user.id, sending.draws)
    _record_sent(user, stored, channels, sending)
    return stored


def _record_sent(
    user: UserDocument, stored: BriefingModel, channels: list[str], sending: Sending
) -> None:
    """Report a delivered brief to analytics and its run's wide event."""
    payload = stored.payload
    capture(
        UserId(user.id),
        BriefingSent(
            kind=stored.kind,
            form=payload.form.value,
            family=payload.template_family,
            mood=payload.mood,
            item_count=sum(len(s.items) for s in payload.sections),
            channel_count=len(channels),
            signal_count=sending.signal_count,
            stamp_collected=payload.new_stamp is not None,
            block_kinds=[block.kind for block in payload.blocks],
            chart_count=sum(1 for block in payload.blocks if isinstance(block, ChartBlock)),
            pool_item_count=sending.pool.items,
            series_count=sending.pool.series,
            source_count=len(payload.sources_read),
        ),
    )
    log.set_ns("briefing", form=payload.form, channels=channels, pushed=sending.push)


async def finish_started_delivery(user: UserDocument, clock: UserClock, kind: BriefingKind) -> bool:
    """Finish today's brief of kind when a run died part-way through delivering it; say whether one was.

    The steps already done are not repeated and nothing is regenerated: the user gets exactly the
    brief its first channels showed. Its analytics event went unsent with the run that died.
    """
    stored = await briefing_repository.find_for_date(user.id, clock.date_str, kind)
    plan = stored.delivery if stored is not None else None
    if plan is None or not plan.done or plan.completed_at is not None:
        return False
    channels = await deliver_brief(user, stored)
    log.set_ns("briefing", resumed=True, channels=channels, pushed=plan.push)
    return True
