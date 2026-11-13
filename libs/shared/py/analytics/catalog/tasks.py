"""Tasks-only comms events: the measures that compare it with the direct executor path."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent

__all__ = [
    "TaskCancelled",
    "TaskFound",
    "TaskMessaged",
    "TaskRead",
    "TaskStarted",
]


class TaskStarted(ServerEvent):
    """Comms turned a request into a task; open_tasks is how many others were open, the continue-or-new context."""

    event: ClassVar[str] = "task:started"
    budget_per_user_day: ClassVar[int] = 200

    timing: Literal["now", "scheduled"]
    visible: bool
    open_tasks: int


class TaskRead(ServerEvent):
    """Comms answered a follow-up from a task's record instead of running it again; level is report or trace."""

    event: ClassVar[str] = "task:read"
    budget_per_user_day: ClassVar[int] = 200

    level: Literal["report", "trace"]
    cross_conversation: bool
    report_age_seconds: int | None = None


class TaskFound(ServerEvent):
    """Comms searched the user's tasks; cross_conversation counts the matches that started in another chat."""

    event: ClassVar[str] = "task:found"
    budget_per_user_day: ClassVar[int] = 200

    results: int
    cross_conversation: int


class TaskMessaged(ServerEvent):
    """Comms steered a task: running joins the run in flight, otherwise the finished task ran again (a re-run)."""

    event: ClassVar[str] = "task:messaged"
    budget_per_user_day: ClassVar[int] = 200

    running: bool
    cross_conversation: bool


class TaskCancelled(ServerEvent):
    """Comms stopped a task at the user's request."""

    event: ClassVar[str] = "task:cancelled"
    budget_per_user_day: ClassVar[int] = 100

    was_running: bool
