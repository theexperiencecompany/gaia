"""Lay the fact pool out as the plain text the composition reads."""

from datetime import date, datetime

from app.agents.prompts.brief_fact_prompts import (
    BACKLOG_STATE,
    CALENDAR_EMPTY_IN,
    CALENDAR_LISTED_IN,
    CALENDAR_UNAVAILABLE,
    DONE_BY,
    ITEM_STATES_LEGEND,
    NO_CALENDAR_CONNECTED,
    ON_ONE_SUBJECT,
    OPEN_STATE,
    POOL_PART_EMPTY,
    POOL_PARTS,
    RECENT_OPENINGS,
    REPEAT_MARK,
    SHOWN_NOT_TOTAL_SERIES,
    SIGNED_OUT_NOTE,
    UNREAD_NOTE,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import UnreadSource
from app.models.brief_pool_models import DataSeries, GoalState, QuoteSpan, SeriesShape
from app.models.scout_models import ScoutSkipReason, SignalImportance
from app.services.briefing.calendar_read import CalendarGap
from app.services.briefing.clock import UserClock
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.scouts.facts import people_note, seen_note
from app.services.briefing.slots import figure, series_figures
from app.utils.timezone import Timezone


def since_note(moment: datetime, clock: UserClock) -> str:
    """Say when the brief's done window opens, on the user's clock: "Sat 14 Nov, 8:00 AM"."""
    local = moment.astimezone(clock.tz)
    return local.strftime("%a %-d %b, %-I:%M %p")


def _day(iso: str, today: date) -> str:
    day = date.fromisoformat(iso)
    label = day.strftime("%a %-d %b")
    return f"{label} (today)" if day == today else label


def item_state(item: BriefCandidate) -> str:
    """Say how an item stands: a calendar event, backlog on their list, or its kind's state."""
    if item.is_event:
        return "calendar event"
    if item.backlog:
        return BACKLOG_STATE
    if item.state is ItemState.LOOKBACK and item.todo_id is not None:
        return DONE_BY[item.finished_by]
    if item.standing is not None:
        return OPEN_STATE
    return item.state.label.lower()


def repeat_note(item: BriefCandidate, clock: UserClock) -> str | None:
    """Say that an earlier brief already showed an item as it stands; None when it is news."""
    if not item.is_repeat or item.memory is None:
        return None
    return f"{REPEAT_MARK} ({seen_note(item.memory, clock)})"


def item_line(item_id: int, item: BriefCandidate, clock: UserClock) -> str:
    """Say one item with every fact its producer knows: its app, state, title and the rest."""
    state = item_state(item)
    head = f"{item_id}. [{item.app}] {state}"
    if item.importance is SignalImportance.HIGH:
        head += ", important"
    parts = [f"{head}: {item.title}"]
    if item.standing is not None:
        parts.append(f"stands: {item.standing}")
    if item.detail:
        parts.append(item.detail)
    if item.time is not None:
        parts.append(f"at {item.time}")
    if item.due_at is not None:
        parts.append(f"due {clock.day_of(item.due_at).isoformat()}")
    if item.people:
        signal = item.signal
        role = signal.people_role if signal is not None and item.people == signal.people else None
        parts.append(people_note(item.people, role, signal.people_you if signal else ()))
    parts += _what_it_asks(item)
    if item.also_in:
        parts.append(f"also found by {', '.join(item.also_in)}")
    if (repeat := repeat_note(item, clock)) is not None:
        parts.append(repeat)
    return " | ".join(parts)


def _what_it_asks(item: BriefCandidate) -> list[str]:
    """Say how many asked, what the producer says it asks or reached, and whether it opens."""
    parts: list[str] = []
    if item.count > 1:
        parts.append(f"{item.count} {ON_ONE_SUBJECT}")
    if item.action is not None:
        parts.append(f"action {item.action.value}")
    if item.outcome is not None:
        parts.append(f"outcome {item.outcome.value}")
    if item.url or item.todo_id:
        parts.append("linkable")
    parts.append(
        "GAIA can act on it" if item.gaia_acts else f"GAIA can only read {item.app}: no offer on it"
    )
    return parts


def series_line(series: DataSeries, today: date) -> str:
    """Say a series' every point and the figures its slots render."""
    if series.shape is SeriesShape.TIME_SERIES:
        laid = "per day: " + " · ".join(f"{_day(p.x, today)} {figure(p.y)}" for p in series.points)
    else:
        laid = "by category: " + " · ".join(f"{p.x} {figure(p.y)}" for p in series.points)
    figures = ", ".join(f"{f.value} {text}" for f, text in series_figures(series).items())
    unit = f", in {series.unit}" if series.unit else ""
    line = (
        f"{series.id} | {series.label}{unit} ({series.app}), {series.shape.value} "
        f"of {len(series.points)} points | {laid} | figures: {figures}"
    )
    return f"{line} | {SHOWN_NOT_TOTAL_SERIES}" if series.shown_not_total else line


def quote_line(quote: QuoteSpan) -> str:
    return f'{quote.id} | {quote.author}, in {quote.app}, on item {quote.item_id}: "{quote.text}"'


def goal_progress(goal: GoalState) -> str:
    """Say what moved on a goal and over which days: who finished its work, and how much is open."""
    since = f" since {date.fromisoformat(goal.since).strftime('%a %-d %b')}" if goal.since else ""
    others = goal.done - goal.done_by_gaia - goal.done_by_you
    owners = [
        f"{n} by {who}"
        for n, who in (
            (goal.done_by_gaia, "GAIA"),
            (goal.done_by_you, "the user"),
            (others, "an event, or no one recorded"),
        )
        if n
    ]
    finished = f"{goal.done} finished{since}" + (f" ({', '.join(owners)})" if owners else "")
    return f"{finished}, {goal.open} open"


def goal_line(goal: GoalState) -> str:
    line = f'{goal.id} | "{goal.statement}" (from {goal.origin.value})'
    if not goal.linked:
        return f"{line} | no todo names what it is about"
    line = f"{line} | linked todos: {goal_progress(goal)}: " + "; ".join(goal.linked)
    return f"{line} | stuck a week or more: {'; '.join(goal.stalled)}" if goal.stalled else line


def pool_block(pool: FactPool) -> str:
    """Lay out every item, series, quote and goal by id; a part with nothing in it says so."""
    clock = pool.context.clock
    today = clock.now_local.date()
    legend = ITEM_STATES_LEGEND.format(done_since=since_note(pool.context.done_since, clock))
    items, series, quotes, goals = POOL_PARTS
    parts = [
        f"{items} ({legend})",
        "\n".join(item_line(i, c, clock) for i, c in pool.items.items()) or POOL_PART_EMPTY,
        series,
        "\n".join(series_line(s, today) for s in pool.series) or POOL_PART_EMPTY,
        quotes,
        "\n".join(quote_line(q) for q in pool.quotes) or POOL_PART_EMPTY,
        goals,
        "\n".join(goal_line(g) for g in pool.goals) or POOL_PART_EMPTY,
    ]
    return "\n".join(parts)


def _calendar_line(context: PoolContext) -> str:
    if context.calendar is CalendarGap.NOT_CONNECTED:
        return NO_CALENDAR_CONNECTED
    if context.calendar is CalendarGap.UNAVAILABLE:
        return CALENDAR_UNAVAILABLE
    if not context.calendar:
        return CALENDAR_EMPTY_IN.format(span=context.calendar_span)
    return CALENDAR_LISTED_IN.format(span=context.calendar_span, count=context.calendar)


def unread_note(unread: list[UnreadSource]) -> str | None:
    """Say which connected apps went unread, and which of them need a reconnect; None when all were read."""
    if not unread:
        return None
    note = UNREAD_NOTE.format(apps=", ".join(dict.fromkeys(source.app for source in unread)))
    signed_out = [s.app for s in unread if s.reason is ScoutSkipReason.SIGNED_OUT]
    if signed_out:
        note += SIGNED_OUT_NOTE.format(apps=", ".join(dict.fromkeys(signed_out)))
    return note


def context_block(context: PoolContext) -> str:
    """Say the day the pool sits in: the date, the calendar's load and how recent briefs opened."""
    lines = [
        f"{context.clock.now_local.strftime('%A %-d %B %Y')}, {Timezone.parse(context.clock.tz)}.",
        _calendar_line(context),
    ]
    if (unread := unread_note(context.unread)) is not None:
        lines.append(unread)
    if context.recent_openings:
        openings = "; ".join(f'"{line}"' for line in context.recent_openings)
        lines.append(RECENT_OPENINGS.format(openings=openings))
    return "\n".join(lines)
