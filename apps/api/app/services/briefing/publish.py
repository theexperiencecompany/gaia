"""Publish a voiced brief: draw its edition, store it, deliver it, persist the draws and report it.

Persistence precedes delivery so the dashboard never misses a brief that reached a channel.
"""

from dataclasses import dataclass, field, replace
from datetime import date

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    DAILY_KICKER,
    QUIET_NOTE_CALENDAR_CLEAR,
    QUIET_NOTE_CALENDAR_UNREAD,
    QUIET_NOTE_HEADLINES,
    QUIET_NOTE_NO_CALENDAR,
    QUIET_NOTE_NOTHING_NEW,
    QUIET_NOTE_OVERDUE,
    QUIET_NOTE_SIGNED_OUT,
    QUIET_NOTE_SIGNED_OUT_MANY,
    QUIET_NOTE_STILL,
    QUIET_NOTE_STILL_FOR,
    QUIET_NOTE_STILL_SINCE,
    QUIET_NOTE_UNREAD,
    QUIET_NOTE_UNREAD_HEADLINE,
    QUIET_NOTE_WATCH,
    WEEKLY_KICKER,
    BriefForm,
)
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_NOTE,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.db.repositories.briefings import briefing_repository
from app.models.brief_composition_models import ChartBlock
from app.models.briefing_models import (
    BriefDelivery,
    BriefingKind,
    BriefingModel,
    BriefingMood,
    BriefingPayload,
    UnreadSource,
)
from app.models.scout_models import ScoutSkipReason
from app.models.user_models import UserDocument
from app.services.analytics_service import capture
from app.services.briefing.context import CalendarGap, UserClock, when_sent
from app.services.briefing.delivery import deliver_brief
from app.services.briefing.edition_draws import BagDraw, draw_stamp_or_artwork, persist_draws
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.postmarks import new_stamp
from app.services.briefing.store import store_brief, store_note
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
    """Whether a brief goes beyond in-app, what it carried and what its pool held."""

    push: bool
    pool: PoolCounts
    signal_count: int = 0
    #: The held results the brief accounts for, consumed once it is delivered.
    held_ids: list[str] = field(default_factory=list)


#: The family a quiet note reports: it is drawn in none.
QUIET_NOTE_FAMILY = "none"

_KICKERS: dict[BriefingKind, str] = {
    BRIEFING_KIND_DAILY: DAILY_KICKER,
    BRIEFING_KIND_WEEKLY: WEEKLY_KICKER,
}

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

    A render failure stores and sends nothing. A brief that is not pushed goes in-app only and
    spends no shuffle-bag draw; otherwise the draws persist after delivery.
    """
    spent = [*draws, *draw_stamp_or_artwork(user, payload)]
    if payload.stamp_city is not None:
        payload.new_stamp = await new_stamp(user.id, payload.stamp_city)
    payload.recipient_name = display_name(user)
    plan = BriefDelivery(
        push=sending.push, notification_kind=_NOTIFICATION_KINDS[kind], held_ids=sending.held_ids
    )
    stored = await store_brief(user.id, clock.date_str, kind, payload, plan)
    channels = await deliver_brief(user, stored)
    if sending.push:
        await persist_draws(user.id, spent)
    _record_sent(
        user,
        stored,
        channels,
        BriefingSent(
            kind=kind,
            form=BriefForm.EDITION.value,
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
    return stored


def _record_sent(
    user: UserDocument, stored: BriefingModel, channels: list[str], sent: BriefingSent
) -> None:
    """Report a delivered brief to analytics and its run's wide event."""
    capture(UserId(user.id), sent)
    plan = stored.delivery
    log.set_ns(
        "briefing",
        kind=stored.kind,
        form=sent.form,
        channels=channels,
        pushed=plan.push if plan is not None else False,
    )


async def finish_started_delivery(user: UserDocument, clock: UserClock, kind: BriefingKind) -> bool:
    """Finish today's brief of kind when a run died part-way through delivering it; say whether one was.

    The steps already done are not repeated and nothing is regenerated: the user gets exactly the
    brief its first channels showed. Its analytics event went unsent with the run that died.
    """
    stored = await briefing_repository.find_for_date(user.id, clock.date_str, kind)
    plan = stored.delivery if stored is not None else None
    if stored is None or plan is None or not plan.done or plan.completed_at is not None:
        return False
    channels = await deliver_brief(user, stored)
    log.set_ns("briefing", kind=kind, resumed=True, channels=channels, pushed=plan.push)
    return True


@dataclass(frozen=True)
class QuietFacts:
    """What a quiet note says beside its quiet: the calendar, the quiet it continues, overdue.

    still_quiet says the brief of its kind before it was a quiet note too; last_edition is the
    last drawn brief of any kind, None when none ever went out.
    """

    calendar: CalendarGap | None
    still_quiet: bool = False
    last_edition: BriefingModel | None = None
    overdue: int = 0
    #: The connected apps that went unread, and why: the quiet is only of what was read.
    unread: list[UnreadSource] = field(default_factory=list)

    @classmethod
    def of(cls, reads: tuple[CalendarGap | None, int, list[UnreadSource]]) -> "QuietFacts":
        """Read what every quiet note states: the calendar's gap, the overdue count, the apps unread."""
        calendar, overdue, unread = reads
        return cls(calendar=calendar, overdue=overdue, unread=unread)

    def apps_unread(self, *reasons: ScoutSkipReason) -> list[str]:
        """Return each unread app once, in order; only those unread for one of reasons, when given."""
        return list(dict.fromkeys(s.app for s in self.unread if not reasons or s.reason in reasons))


def last_was_quiet(recent: list[BriefingModel], kind: BriefingKind) -> bool:
    """Say whether the latest brief of its kind, of the recent ones newest first, was a quiet note."""
    previous = next((b for b in recent if b.kind == kind), None)
    return previous is not None and previous.payload.form is BriefForm.QUIET_NOTE


async def quiet_facts(
    user_id: str,
    kind: BriefingKind,
    recent: list[BriefingModel],
    reads: tuple[CalendarGap | None, int, list[UnreadSource]],
) -> QuietFacts:
    """Say how the quiet stands: what was read, and after a quiet brief of its kind the last edition."""
    facts = QuietFacts.of(reads)
    if not last_was_quiet(recent, kind):
        return facts
    editions = await briefing_repository.list_recent(user_id, limit=1, editions_only=True)
    return replace(facts, still_quiet=True, last_edition=editions[0] if editions else None)


def _quiet_news(kind: BriefingKind, facts: QuietFacts, clock: UserClock) -> str:
    """Say there is nothing new; after a quiet brief, since which brief and how many days ago."""
    if not facts.still_quiet:
        return QUIET_NOTE_UNREAD_HEADLINE if facts.unread else QUIET_NOTE_NOTHING_NEW[kind]
    edition = facts.last_edition
    if edition is None:
        return QUIET_NOTE_STILL
    when = when_sent(edition, clock)
    days = (clock.now_local.date() - date.fromisoformat(edition.date)).days
    if days == 1:
        return QUIET_NOTE_STILL_SINCE.format(when=when)
    return QUIET_NOTE_STILL_FOR.format(days=days, when=when)


def quiet_note(clock: UserClock, kind: BriefingKind, facts: QuietFacts) -> BriefingPayload:
    """Write a quiet brief's note from its facts: nothing new, the calendar, what is past due."""
    calendar = {
        None: QUIET_NOTE_CALENDAR_CLEAR[kind],
        CalendarGap.NOT_CONNECTED: QUIET_NOTE_NO_CALENDAR,
        CalendarGap.UNAVAILABLE: QUIET_NOTE_CALENDAR_UNREAD,
    }[facts.calendar]
    lines = [f"{_quiet_news(kind, facts, clock)}{calendar}"]
    if facts.unread:
        lines.append(QUIET_NOTE_UNREAD.format(apps=" or ".join(facts.apps_unread())))
    if signed_out := facts.apps_unread(ScoutSkipReason.SIGNED_OUT):
        reconnect = QUIET_NOTE_SIGNED_OUT_MANY if len(signed_out) > 1 else QUIET_NOTE_SIGNED_OUT
        lines.append(reconnect.format(apps=" and ".join(signed_out)))
    if facts.overdue:
        lines.append(QUIET_NOTE_OVERDUE.format(count=facts.overdue))
    lines.append(QUIET_NOTE_WATCH)
    return BriefingPayload(
        form=BriefForm.QUIET_NOTE,
        kicker=_KICKERS[kind],
        date=clock.date_str,
        headline=QUIET_NOTE_UNREAD_HEADLINE if facts.unread else QUIET_NOTE_HEADLINES[kind],
        lede="",
        caption="",
        mood=BriefingMood.IDLE,
        template_family="",
        message="\n".join(lines),
        sources_unavailable=facts.unread,
    )


async def publish_quiet_note(
    user: UserDocument,
    clock: UserClock,
    kind: BriefingKind,
    payload: BriefingPayload,
    sending: Push,
) -> BriefingModel:
    """Store and deliver a quiet brief's note: no edition is drawn, rendered or spent."""
    plan = BriefDelivery(
        push=True, notification_kind=NOTIFICATION_KIND_BRIEFING_NOTE, held_ids=sending.held_ids
    )
    stored = await store_note(user.id, clock.date_str, kind, payload, plan)
    channels = await deliver_brief(user, stored)
    _record_sent(
        user,
        stored,
        channels,
        BriefingSent(
            kind=kind,
            form=BriefForm.QUIET_NOTE.value,
            family=QUIET_NOTE_FAMILY,
            mood=payload.mood,
            item_count=0,
            channel_count=len(channels),
            signal_count=0,
            stamp_collected=False,
            block_kinds=[],
            chart_count=0,
            pool_item_count=sending.pool.items,
            series_count=sending.pool.series,
            source_count=0,
        ),
    )
    return stored
