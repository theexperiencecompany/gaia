"""Lay the fact pool out as the plain text the composition reads."""

from datetime import date

from app.constants.briefing import (
    BACKLOG_STATE,
    CALENDAR_UNAVAILABLE,
    NO_CALENDAR_CONNECTED,
    REPEAT_MARK,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_pool_models import DataSeries, GoalState, QuoteSpan, SeriesShape
from app.models.briefing_models import BRIEFING_ITEM_STATES
from app.models.scout_models import SignalImportance
from app.services.briefing.context import CalendarGap, UserClock
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.scouts.facts import seen_note
from app.services.briefing.slots import figure, series_figures

# What each item state means, said beside the items so every reader of the pool reads them alike.
_STATES = (
    "done: finished since the last brief, overnight; in progress: still running; "
    "waiting on you: needs the user; failed: broke and needs the user; note: news that needs nothing; "
    f"{BACKLOG_STATE}: an undated todo of their own, never news and never the lead. "
    f"An item marked {REPEAT_MARK} was already shown, unchanged: not news, so it never leads"
)


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
    return BRIEFING_ITEM_STATES[item.state].lower()


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
    if item.detail:
        parts.append(item.detail)
    if item.time is not None:
        parts.append(f"at {item.time}")
    if item.due_at is not None:
        parts.append(f"due {clock.day_of(item.due_at).isoformat()}")
    if item.people:
        parts.append(f"with {', '.join(item.people)}")
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
        parts.append(f"{item.count} requests, one item")
    if item.action is not None:
        parts.append(f"action {item.action.value}")
    if item.outcome is not None:
        parts.append(f"outcome {item.outcome.value}")
    if item.url or item.todo_id:
        parts.append("linkable")
    return parts


def series_line(series: DataSeries, today: date) -> str:
    """Say a series' every point and the figures its slots render."""
    if series.shape is SeriesShape.TIME_SERIES:
        laid = "per day: " + " · ".join(f"{_day(p.x, today)} {figure(p.y)}" for p in series.points)
    else:
        laid = "by category: " + " · ".join(f"{p.x} {figure(p.y)}" for p in series.points)
    figures = ", ".join(f"{f.value} {text}" for f, text in series_figures(series).items())
    unit = f", in {series.unit}" if series.unit else ""
    return (
        f"{series.id} | {series.label}{unit} ({series.app}), {series.shape.value} "
        f"of {len(series.points)} points | {laid} | figures: {figures}"
    )


def quote_line(quote: QuoteSpan) -> str:
    return f'{quote.id} | {quote.author}, in {quote.app}, on item {quote.item_id}: "{quote.text}"'


def goal_line(goal: GoalState) -> str:
    line = f'{goal.id} | "{goal.statement}" (from {goal.origin.value})'
    if not goal.linked:
        return f"{line} | no todo names what it is about"
    return (
        f"{line} | linked todos: {goal.done} finished in the window, {goal.open} open: "
        + "; ".join(goal.linked)
    )


def pool_block(pool: FactPool) -> str:
    """Lay out every item, series, quote and goal by id; a part with nothing in it says so."""
    clock = pool.context.clock
    today = clock.now_local.date()
    parts = [
        f"ITEMS ({_STATES})",
        "\n".join(item_line(i, c, clock) for i, c in pool.items.items()) or "(none)",
        "SERIES",
        "\n".join(series_line(s, today) for s in pool.series) or "(none)",
        "QUOTES",
        "\n".join(quote_line(q) for q in pool.quotes) or "(none)",
        "GOALS",
        "\n".join(goal_line(g) for g in pool.goals) or "(none)",
    ]
    return "\n".join(parts)


def _calendar_line(context: PoolContext) -> str:
    if context.calendar is CalendarGap.NOT_CONNECTED:
        return NO_CALENDAR_CONNECTED
    if context.calendar is CalendarGap.UNAVAILABLE:
        return CALENDAR_UNAVAILABLE
    if not context.calendar:
        return f"Nothing on the calendar {context.calendar_span}."
    return f"Calendar {context.calendar_span}: {context.calendar} event(s), every one listed below."


def context_block(context: PoolContext) -> str:
    """Say the day the pool sits in: the date, the calendar's load and how recent briefs opened."""
    lines = [
        f"{context.clock.now_local.strftime('%A %-d %B %Y')}, {context.clock.tz.key}.",
        _calendar_line(context),
    ]
    if context.recent_openings:
        lines.append(
            "Recent briefs opened on: "
            + "; ".join(f'"{line}"' for line in context.recent_openings)
            + ". Lead somewhere new unless the same thing still matters most."
        )
    return "\n".join(lines)
