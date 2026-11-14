"""Goals: what the user said they work toward, with the todos that name what each goal is about.

A goal from memory carries the names its memory is about (a project, a company, a
person); a todo whose title names one of them, as a whole word, is linked work. A goal
with no names (the onboarding focus) has none: it is stated, never guessed at.
"""

from collections.abc import Sequence
import re

from app.models.brief_pool_models import GoalState
from app.models.todo_models import TodoDocument
from app.services.briefing.context import StatedGoal


def _names(goal: StatedGoal) -> list[re.Pattern[str]]:
    return [
        re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        for term in goal.terms
        if term.strip()
    ]


def goal_states(goals: Sequence[StatedGoal], todos: Sequence[TodoDocument]) -> list[GoalState]:
    """Return each goal with the finished and open todos linked to it, numbered g1 up.

    todos are the ones the brief read: finished in its window, or still open.
    """
    states: list[GoalState] = []
    for goal in goals:
        names = _names(goal)
        linked = [t for t in todos if any(n.search(t.title) for n in names)]
        done = [t.title for t in linked if t.completed]
        still_open = [t.title for t in linked if not t.completed]
        states.append(
            GoalState(
                id=f"g{len(states) + 1}",
                statement=goal.statement,
                origin=goal.origin,
                done=len(done),
                open=len(still_open),
                linked=[*done, *still_open],
            )
        )
    return states
