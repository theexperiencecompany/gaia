"""Goals: what the user said they work toward, with the todos that name what each goal is about.

A goal from memory carries the names its memory is about (a project, a company, a
person); a todo whose title names one of them, as a whole word, is linked work. A goal
with no names (the onboarding focus) has none: it is stated, never guessed at.
"""

from collections.abc import Sequence
from datetime import date, datetime
import re

from app.constants.briefing import GOAL_WORK_STALLED_AFTER
from app.constants.todos import TodoCompleter
from app.models.brief_pool_models import GoalState
from app.models.todo_models import TodoDocument
from app.services.briefing.context import StatedGoal, finished_by
from app.utils.timezone import as_utc


def _names(goal: StatedGoal) -> list[re.Pattern[str]]:
    return [
        re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        for term in goal.terms
        if term.strip()
    ]


def _stuck(todo: TodoDocument, now: datetime) -> bool:
    """Whether an open todo has gone untouched for GOAL_WORK_STALLED_AFTER; an undated one never has."""
    touched = as_utc(todo.updated_at or todo.created_at)
    return touched is not None and now - touched >= GOAL_WORK_STALLED_AFTER


def goal_states(
    goals: Sequence[StatedGoal], todos: Sequence[TodoDocument], now: datetime, since: date
) -> list[GoalState]:
    """Return each goal with the finished (by whom), open and stuck todos linked to it, numbered g1 up.

    todos are the ones the brief read: finished in its window, opening on since, or still open.
    """
    states: list[GoalState] = []
    for goal in goals:
        names = _names(goal)
        linked = [t for t in todos if any(n.search(t.title) for n in names)]
        finished = [t for t in linked if t.completed]
        done = [t.title for t in finished]
        by = [finished_by(t) for t in finished]
        still_open = [t for t in linked if not t.completed]
        states.append(
            GoalState(
                id=f"g{len(states) + 1}",
                statement=goal.statement,
                origin=goal.origin,
                done=len(done),
                done_by_gaia=by.count(TodoCompleter.GAIA),
                done_by_you=by.count(TodoCompleter.USER),
                since=since.isoformat(),
                open=len(still_open),
                linked=[*done, *(t.title for t in still_open)],
                stalled=[t.title for t in still_open if _stuck(t, now)],
            )
        )
    return states
