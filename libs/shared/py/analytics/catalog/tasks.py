"""Task events: to-dos the user does and work GAIA does, once or on repeat."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.delivery import ProactiveDestinationBasis, ProactiveDestinationKind
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "EventFireOutcome",
    "NudgeChannel",
    "TaskChatOpened",
    "TaskCreated",
    "TaskDeleted",
    "TaskEventFired",
    "TaskNudged",
    "TaskOpenStateRepaired",
    "TaskRunFailed",
    "TaskRunResultDelivered",
    "TaskSubscribeFailed",
    "TaskSubscribeFailureReason",
    "TaskSubscribed",
    "TaskToggled",
    "TaskUpdated",
]

#: Where a to-do's nudge reached the user.
NudgeChannel = Literal["in_app", "chat_app"]
#: Why GAIA could not subscribe a task to an app event.
TaskSubscribeFailureReason = Literal[
    "unknown_trigger",
    "not_a_gaia_task",
    "invalid_conditions",
    "invalid_config",
    "invalid_subscription",
    "registration_failed",
    "no_trigger_instance",
]
#: What a matched app event does to its task's run: runs it now, rides the run its window
#: already has, waits for the user's quiet hours to end, or waits for the task to resume.
EventFireOutcome = Literal["ran", "coalesced", "held_for_quiet_hours", "kept_while_paused"]


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


class TaskRunResultDelivered(ServerEvent):
    """A GAIA task's run result reached, or failed to reach, the user; destination is where it was routed."""

    event: ClassVar[str] = "task:run_result_delivered"
    # One per run: an hourly task alone delivers 24 a day.
    budget_per_user_day: ClassVar[int] = 50

    task_id: Identifier
    outcome: Identifier
    delivered: bool
    trigger_type: Identifier
    repeats: bool
    platform: Identifier | None = None
    destination: ProactiveDestinationKind | None = None
    destination_basis: ProactiveDestinationBasis | None = None


class TaskChatOpened(ServerEvent):
    """A user opened a GAIA task's chat from the task."""

    event: ClassVar[str] = "task:chat_opened"
    budget_per_user_day: ClassVar[int] = 100

    task_id: Identifier


class TaskRunFailed(ServerEvent):
    """A GAIA task's run failed and will not be retried: the task is marked failed."""

    event: ClassVar[str] = "task:run_failed"
    budget_per_user_day: ClassVar[int] = 20

    task_id: Identifier
    attempts: int


class TaskOpenStateRepaired(ServerEvent):
    """A one-off GAIA task's run ended with no next step, so code set one."""

    event: ClassVar[str] = "task:open_state_repaired"
    budget_per_user_day: ClassVar[int] = 20

    task_id: Identifier
    # What the task was waiting on when the run that left it without a next step woke.
    waiting_on: Identifier | None = None


class TaskNudged(ServerEvent):
    """A to-do came round (fell due, or came back on its repeat) and the user was told."""

    event: ClassVar[str] = "task:nudged"
    budget_per_user_day: ClassVar[int] = 100

    task_id: Identifier
    repeats: bool
    channel: NudgeChannel
    #: The nudge was held through the user's quiet hours and sent when they ended.
    held_for_quiet_hours: bool


class TaskSubscribed(ServerEvent):
    """GAIA subscribed one of its tasks to an app event."""

    event: ClassVar[str] = "task:subscribed"
    budget_per_user_day: ClassVar[int] = 20

    task_id: Identifier
    trigger_name: Identifier
    condition_count: int
    #: Conditions GAIA wrote that were repaired (a camelCased field, a mistyped value).
    repaired: bool
    has_gate: bool


class TaskSubscribeFailed(ServerEvent):
    """GAIA could not subscribe a task to an app event."""

    event: ClassVar[str] = "task:subscribe_failed"
    budget_per_user_day: ClassVar[int] = 20

    trigger_name: Identifier
    reason: TaskSubscribeFailureReason


class TaskEventFired(ServerEvent):
    """An app event passed a task subscription's conditions and gate and was taken for a run."""

    event: ClassVar[str] = "task:event_fired"
    budget_per_user_day: ClassVar[int] = 50

    task_id: Identifier
    trigger_name: Identifier
    outcome: EventFireOutcome
