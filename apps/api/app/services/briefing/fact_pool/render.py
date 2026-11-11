"""Lay the fact pool out as the plain text the composition reads."""

from datetime import date

from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_pool_models import DataSeries, GoalState, QuoteSpan, SeriesShape
from app.models.briefing_models import BRIEFING_ITEM_STATES
from app.models.scout_models import SignalImportance
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.slots import figure, series_figures

# What each item state means, said beside the items so every reader of the pool reads them alike.
_STATES = (
    "done: finished since the last brief, overnight; in progress: still running; "
    "waiting on you: needs the user; failed: broke and needs the user; note: news that needs nothing"
)


def _day(iso: str, today: date) -> str:
    day = date.fromisoformat(iso)
    label = day.strftime("%a %-d %b")
    return f"{label} (today)" if day == today else label


def item_line(item_id: int, item: BriefCandidate) -> str:
    """Say one item with every fact its producer knows: its app, state, title and the rest."""
    state = "calendar event" if item.is_event else BRIEFING_ITEM_STATES[item.state].lower()
    head = f"{item_id}. [{item.app}] {state}"
    if item.importance is SignalImportance.HIGH:
        head += ", important"
    parts = [f"{head}: {item.title}"]
    if item.detail:
        parts.append(item.detail)
    if item.time is not None:
        parts.append(f"at {item.time}")
    if item.due_at is not None:
        parts.append(f"due {item.due_at.date().isoformat()}")
    if item.people:
        parts.append(f"with {', '.join(item.people)}")
    if item.count > 1:
        parts.append(f"{item.count} requests, one item")
    if item.action is not None:
        parts.append(f"action {item.action.value}")
    if item.outcome is not None:
        parts.append(f"outcome {item.outcome.value}")
    if item.url or item.todo_id:
        parts.append("linkable")
    if item.also_in:
        parts.append(f"also found by {', '.join(item.also_in)}")
    return " | ".join(parts)


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
    today = pool.context.today
    parts = [
        f"ITEMS ({_STATES})",
        "\n".join(item_line(i, c) for i, c in pool.items.items()) or "(none)",
        "SERIES",
        "\n".join(series_line(s, today) for s in pool.series) or "(none)",
        "QUOTES",
        "\n".join(quote_line(q) for q in pool.quotes) or "(none)",
        "GOALS",
        "\n".join(goal_line(g) for g in pool.goals) or "(none)",
    ]
    return "\n".join(parts)


def context_block(context: PoolContext) -> str:
    """Say the day the pool sits in: the date, the calendar's load and how recent briefs opened."""
    lines = [
        f"{context.today.strftime('%A %-d %B %Y')}, {context.timezone}.",
        f"Calendar {context.calendar_span}: {context.calendar_events} event(s), every one listed below."
        if context.calendar_events
        else f"Nothing on the calendar {context.calendar_span}.",
    ]
    if context.recent_openings:
        lines.append(
            "Recent briefs opened on: "
            + "; ".join(f'"{line}"' for line in context.recent_openings)
            + ". Lead somewhere new unless the same thing still matters most."
        )
    return "\n".join(lines)
