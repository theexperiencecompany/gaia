"""The fact pool: everything a brief can say, built by code for one user and read-only to the model.

Items come from the candidate producers; series, quotes and goals from their producers
here. The composition places these by id, and nothing outside the pool can be placed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.constants.briefing import BRIEFING_RHYTHM_WORKFLOW_KEYS
from app.db.repositories.email_verdicts import email_verdict_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_pool_models import DataSeries, GoalState, QuoteSpan
from app.models.calendar_models import GoogleCalendarEventResource
from app.models.scout_models import Signal
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.services.briefing.context import StatedGoal
from app.services.briefing.fact_pool.calendar_series import calendar_series
from app.services.briefing.fact_pool.goals import goal_states
from app.services.briefing.fact_pool.mail_series import (
    SORT_SPAN,
    sorted_mail_series,
    thread_series,
)
from app.services.briefing.fact_pool.quotes import quote_spans
from app.services.briefing.fact_pool.run_series import run_series
from app.services.briefing.fact_pool.signal_series import signal_series
from app.services.briefing.fact_pool.window import SeriesWindow
from app.services.briefing.fact_pool.work_series import work_series

# The open todos a goal's linked work is read from: the user's own, and GAIA's tracked ones.
_OPEN_USER_TODOS_READ = 50
_OPEN_TRACKED_TODOS_READ = 20


@dataclass(frozen=True)
class PoolContext:
    """Who the brief is for and the shape of their day, which the composition reads beside the pool."""

    reader: str
    timezone: str
    today: date
    #: The calendar events the brief's span holds, and the span: "today", "in the week ahead".
    calendar_events: int
    calendar_span: str
    #: The opening line of each recent brief, newest first, so today's opens differently.
    recent_openings: list[str]


@dataclass(frozen=True)
class FactPool:
    """Every item, series, quote and goal one brief can place, by id, and the context they sit in."""

    items: Mapping[int, BriefCandidate]
    series: list[DataSeries]
    quotes: list[QuoteSpan]
    goals: list[GoalState]
    context: PoolContext
    #: How each app's scout tells what needs this user, by the app's display name.
    criteria: Mapping[str, str]

    @property
    def composable(self) -> bool:
        """Whether there is anything to compose besides the calendar, which the edition draws itself."""
        news = any(not c.is_event for c in self.items.values())
        return news or bool(self.series or self.quotes or self.goals)

    @property
    def series_by_id(self) -> dict[str, DataSeries]:
        return {s.id: s for s in self.series}

    @property
    def quotes_by_id(self) -> dict[str, QuoteSpan]:
        return {q.id: q for q in self.quotes}

    @property
    def goals_by_id(self) -> dict[str, GoalState]:
        return {g.id: g for g in self.goals}


@dataclass(frozen=True)
class PoolReads:
    """What the run already read that the pool is built from."""

    items: Mapping[int, BriefCandidate]
    signals: Sequence[Signal]
    #: The calendar over the series window, as Google sent it.
    calendar: Sequence[GoogleCalendarEventResource]
    goals: Sequence[StatedGoal]
    criteria: Mapping[str, str]


def _distinct(todos: Sequence[TodoDocument]) -> list[TodoDocument]:
    return list({t.id: t for t in todos}.values())


async def _series(
    user_id: str, window: SeriesWindow, reads: PoolReads, now: datetime
) -> tuple[list[DataSeries], list[TodoDocument]]:
    """Run every series producer over the window; return the series and the todos finished in it."""
    completed = await todo_repository.list_completed_since(user_id, since=window.start)
    threads = await todo_repository.list_external_ref_activity_since(
        user_id, ExternalRefSource.GMAIL_THREAD, since=window.start
    )
    verdicts = await email_verdict_repository.list_since(user_id, since=now - SORT_SPAN)
    rhythm = await workflow_repository.find_system_workflows(user_id, BRIEFING_RHYTHM_WORKFLOW_KEYS)
    runs = await workflow_executions_repository.list_run_moments_since(
        user_id, window.start, exclude_workflow_ids=[w.id for w in rhythm]
    )
    series = [
        *work_series(completed, window),
        *calendar_series(reads.calendar, window),
        *thread_series(threads, window),
        *sorted_mail_series(verdicts),
        *run_series(runs, window),
        *signal_series(reads.signals),
    ]
    return series, completed


async def build_fact_pool(
    user_id: str, window: SeriesWindow, reads: PoolReads, context: PoolContext, now: datetime
) -> FactPool:
    """Build the brief's fact pool: the numbered items, then every series, quote and goal."""
    series, completed = await _series(user_id, window, reads, now)
    open_todos = [
        *await todo_repository.list_open_user_todos(user_id, limit=_OPEN_USER_TODOS_READ),
        *await todo_repository.list_active_tracked(user_id, limit=_OPEN_TRACKED_TODOS_READ),
    ]
    return FactPool(
        items=reads.items,
        series=series,
        quotes=quote_spans(reads.items),
        goals=goal_states(reads.goals, _distinct([*completed, *open_todos])),
        context=context,
        criteria=reads.criteria,
    )
