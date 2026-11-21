"""Task events: to-dos the user does and work GAIA does, once or on repeat."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "NudgeChannel",
    "TaskCreated",
    "TaskDeleted",
    "TaskNudged",
    "TaskToggled",
    "TaskUpdated",
]

#: Where a to-do's nudge reached the user.
NudgeChannel = Literal["in_app", "chat_app"]


class TaskCreated(ServerEvent):
    """The user made a task."""

    event: ClassVar[str] = "task:created"
    budget_per_user_day: ClassVar[int] = 200

    task_id: Identifier
    assignee: Identifier
    when_kind: Identifier
    priority: Identifier
    has_body: bool
    checklist_count: int
    is_subtask: bool


class TaskUpdated(ServerEvent):
    """The user edited a task or its checklist."""

    event: ClassVar[str] = "task:updated"
    budget_per_user_day: ClassVar[int] = 50

    task_id: Identifier
    changed_fields: list[Identifier]
    is_checklist: bool = False


class TaskToggled(ServerEvent):
    """A task or a checklist item was ticked off or reopened."""

    event: ClassVar[str] = "task:toggled"
    budget_per_user_day: ClassVar[int] = 500

    completed: bool
    task_id: Identifier | None = None
    is_checklist: bool = False
    bulk_count: int | None = None


class TaskDeleted(ServerEvent):
    """The user deleted one task or several, with the subtasks filed under them."""

    event: ClassVar[str] = "task:deleted"
    budget_per_user_day: ClassVar[int] = 20

    count: int


class TaskNudged(ServerEvent):
    """A to-do came round (fell due, or came back on its repeat) and the user was told."""

    event: ClassVar[str] = "task:nudged"
    budget_per_user_day: ClassVar[int] = 100

    task_id: Identifier
    repeats: bool
    channel: NudgeChannel
    #: The nudge was held through the user's quiet hours and sent when they ended.
    held_for_quiet_hours: bool
