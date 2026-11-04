"""What a finished scheduled run of a non-recurring tracked todo leaves behind.

The run spent the check that woke it. It either closed the todo, set a new
next step (scheduled_at moved), or neither. For neither, code must not leave the
todo asleep: it parks it for tomorrow, or closes it when its question ran out of
holds. This module decides; the worker applies the decision with its own writes.
"""

from enum import StrEnum

from app.models.todo_models import TodoDocument
from app.services.todos.open_state import hold_ran_out


class Settlement(StrEnum):
    """What to do with a todo once its scheduled run ended."""

    NOTHING = "nothing"
    END_CHECK = "end_check"
    CLOSE_UNANSWERED = "close_unanswered"
    PARK_AS_UNPLANNED = "park_as_unplanned"


def settle(woke: TodoDocument, current: TodoDocument | None) -> Settlement:
    """Decide what the ended run leaves to do; woke is the todo as the run found it.

    current is the todo now, or None when it was deleted. The run closed the todo
    or moved its next check when either shows in current: that run's work stands.
    """
    if current is None or current.completed or current.scheduled_at != woke.scheduled_at:
        return Settlement.NOTHING
    if current.pause_reason is not None:
        return Settlement.END_CHECK
    if hold_ran_out(current):
        return Settlement.CLOSE_UNANSWERED
    return Settlement.PARK_AS_UNPLANNED
