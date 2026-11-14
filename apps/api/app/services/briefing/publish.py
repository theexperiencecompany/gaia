"""Publish a voiced brief: draw its edition, store it, deliver it, persist the draws and report it.

Persistence precedes delivery so the dashboard never misses a brief that reached a channel.
"""

from dataclasses import dataclass
from itertools import takewhile

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
    QUIET_NOTE_RUN_UNITS,
    QUIET_NOTE_STILL,
    QUIET_NOTE_STILL_SINCE,
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
from app.models.briefing_models import (
    BriefingKind,
    BriefingModel,
    BriefingPayload,
)
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
    """Whether a brief goes beyond in-app, how many app signals it carried, and what its pool held."""

    push: bool
    pool: PoolCounts
    signal_count: int = 0


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
            form=BriefForm.EDITION.value,
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


@dataclass(frozen=True)
class QuietFacts:
    """What a quiet note says beside its quiet: the calendar, the quiet streak it continues, overdue.

    quiet_run counts the quiet notes in a row this one makes, itself included; last_edition is
    when the last drawn brief went out, said as the user would, None when no recent one was.
    """

    calendar: CalendarGap | None
    quiet_run: int = 1
    last_edition: str | None = None
    overdue: int = 0


def quiet_facts(
    recent: list[BriefingModel], clock: UserClock, calendar: CalendarGap | None, overdue: int
) -> QuietFacts:
    """Read the quiet streak off the recent briefs, newest first, every kind among them."""
    quiet = list(takewhile(lambda b: b.payload.form is BriefForm.QUIET_NOTE, recent))
    edition = next((b for b in recent if b.payload.form is BriefForm.EDITION), None)
    return QuietFacts(
        calendar=calendar,
        quiet_run=len(quiet) + 1,
        last_edition=when_sent(edition, clock) if edition is not None else None,
        overdue=overdue,
    )


def _quiet_news(kind: BriefingKind, facts: QuietFacts) -> str:
    """Say there is nothing new; after a quiet brief, how long it has stayed so and since when."""
    if facts.quiet_run == 1:
        return QUIET_NOTE_NOTHING_NEW[kind]
    if facts.last_edition is None:
        return QUIET_NOTE_STILL
    return QUIET_NOTE_STILL_SINCE.format(
        run=facts.quiet_run, unit=QUIET_NOTE_RUN_UNITS[kind], when=facts.last_edition
    )


def quiet_note(clock: UserClock, kind: BriefingKind, facts: QuietFacts) -> BriefingPayload:
    """Write a quiet brief's note from its facts: nothing new, the calendar, what is past due."""
    calendar = {
        None: QUIET_NOTE_CALENDAR_CLEAR[kind],
        CalendarGap.NOT_CONNECTED: QUIET_NOTE_NO_CALENDAR,
        CalendarGap.UNAVAILABLE: QUIET_NOTE_CALENDAR_UNREAD,
    }[facts.calendar]
    lines = [f"{_quiet_news(kind, facts)}{calendar}"]
    if facts.overdue:
        lines.append(QUIET_NOTE_OVERDUE.format(count=facts.overdue))
    lines.append(QUIET_NOTE_WATCH)
    return BriefingPayload(
        form=BriefForm.QUIET_NOTE,
        kicker=_KICKERS[kind],
        date=clock.date_str,
        headline=QUIET_NOTE_HEADLINES[kind],
        lede="",
        caption="",
        mood="idle",
        template_family="",
        message="\n".join(lines),
    )


async def publish_quiet_note(
    user: UserDocument,
    clock: UserClock,
    kind: BriefingKind,
    payload: BriefingPayload,
    pool: PoolCounts,
) -> BriefingModel:
    """Store and deliver a quiet brief's note: no edition is drawn, rendered or spent."""
    stored = await store_note(user.id, clock.date_str, kind, payload)
    channels = await deliver_brief(
        user, stored, payload, NOTIFICATION_KIND_BRIEFING_NOTE, push=True
    )
    await briefing_repository.set_delivered_channels(user.id, clock.date_str, kind, channels)
    capture(
        UserId(user.id),
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
            pool_item_count=pool.items,
            series_count=pool.series,
            source_count=0,
        ),
    )
    log.info(
        "briefing.sent",
        user_id=user.id,
        kind=kind,
        channels=channels,
        form="quiet_note",
    )
    return stored.briefing
