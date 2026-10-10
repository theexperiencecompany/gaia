"""Todo and project events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier, ObjectIdStr

__all__ = [
    "ProjectsCreated",
    "ProjectsDeleted",
    "ProjectsUpdated",
    "TodosCreated",
    "TodosDeleted",
    "TodosInboxDeskProvisioned",
    "TodosRunResultDelivered",
    "TodosSubscriptionFailed",
    "TodosSubscriptionRegistered",
    "TodosToggled",
    "TodosTriggerFired",
    "TodosUpdated",
    "TodosViewChanged",
]

SubscriptionFailureReason = Literal[
    "unknown_trigger",
    "todo_not_found",
    "invalid_conditions",
    "invalid_config",
    "registration_failed",
    "no_trigger_instance",
    "write_conflict",
]


class TodosCreated(ServerEvent):
    """A user created a todo."""

    event: ClassVar[str] = "todos:created"

    priority: Identifier
    has_due_date: bool
    has_description: bool
    labels_count: int
    subtasks_count: int
    has_project: bool
    is_sub_todo: bool


class TodosUpdated(ServerEvent):
    """A user edited a todo, a subtask, or a bulk selection of todos."""

    event: ClassVar[str] = "todos:updated"

    todo_id: ObjectIdStr | None = None
    changed_field_count: int | None = None
    changed_fields: list[Identifier] | None = None
    priority: Identifier | None = None
    has_due_date: bool | None = None
    has_subtasks: bool | None = None
    bulk_count: int | None = None
    is_subtask: bool | None = None


class TodosToggled(ServerEvent):
    """A todo or subtask was completed or un-completed; one event for both directions."""

    event: ClassVar[str] = "todos:toggled"

    todo_id: ObjectIdStr | None = None
    completed: bool | None = None
    priority: Identifier | None = None
    has_due_date: bool | None = None
    is_subtask: bool | None = None
    bulk_count: int | None = None
    count: int | None = None


class TodosDeleted(ServerEvent):
    """A user deleted one todo or several."""

    event: ClassVar[str] = "todos:deleted"

    todo_id: ObjectIdStr | None = None
    count: int | None = None


class TodosSubscriptionRegistered(ServerEvent):
    """A trigger subscription was stored on a tracked todo."""

    event: ClassVar[str] = "todos:subscription_registered"

    trigger_name: Identifier
    action: Identifier
    resolution: Identifier
    condition_count: int
    repaired: bool
    cooldown_seconds: int


class TodosSubscriptionFailed(ServerEvent):
    """A trigger subscription could not be registered on a tracked todo."""

    event: ClassVar[str] = "todos:subscription_failed"

    trigger_name: Identifier
    reason: SubscriptionFailureReason


class TodosTriggerFired(ServerEvent):
    """A subscribed trigger passed its conditions and cooldown and ran its action."""

    event: ClassVar[str] = "todos:trigger_fired"

    trigger_name: Identifier
    action: Identifier
    resolution: Identifier
    condition_count: int
    # The event landed inside a run window already claimed, so it rides that next run.
    coalesced: bool


class TodosRunResultDelivered(ServerEvent):
    """A tracked todo's run result reached, or failed to reach, the user's chat app."""

    event: ClassVar[str] = "todos:run_result_delivered"

    outcome: Identifier
    delivered: bool
    trigger_type: Identifier
    recurring: bool
    platform: Identifier | None = None


class TodosInboxDeskProvisioned(ServerEvent):
    """The user's Inbox desk tracked todo exists and its first morning run is armed."""

    event: ClassVar[str] = "todos:inbox_desk_provisioned"


class ProjectsCreated(ServerEvent):
    """A user created a todo project."""

    event: ClassVar[str] = "projects:created"


class ProjectsUpdated(ServerEvent):
    """A user updated a todo project."""

    event: ClassVar[str] = "projects:updated"


class ProjectsDeleted(ServerEvent):
    """A user deleted a todo project."""

    event: ClassVar[str] = "projects:deleted"


class TodosViewChanged(WebEvent):
    """A user switched todo views in the sidebar; pure client navigation."""

    event: ClassVar[str] = "todos:view_changed"

    # The kind of view opened, never its path: a label view's path carries the user's label name.
    view_kind: Literal[
        "inbox",
        "today",
        "upcoming",
        "completed",
        "priority_high",
        "priority_medium",
        "priority_low",
        "label",
        "project",
    ]
