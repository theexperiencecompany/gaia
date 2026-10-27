"""Todo and project events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.delivery import ProactiveDestinationBasis, ProactiveDestinationKind
from shared.py.analytics.catalog.properties import Identifier, ObjectIdStr

__all__ = [
    "ProjectsCreated",
    "ProjectsDeleted",
    "ProjectsUpdated",
    "SubscriptionFailureReason",
    "TodosChatOpened",
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
]


class TodosCreated(ServerEvent):
    """A user created a todo."""

    event: ClassVar[str] = "todos:created"
    budget_per_user_day: ClassVar[int] = 200

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
    budget_per_user_day: ClassVar[int] = 20

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
    budget_per_user_day: ClassVar[int] = 500

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
    budget_per_user_day: ClassVar[int] = 10

    todo_id: ObjectIdStr | None = None
    count: int | None = None


class TodosSubscriptionRegistered(ServerEvent):
    """A trigger subscription was stored on a tracked todo."""

    event: ClassVar[str] = "todos:subscription_registered"
    budget_per_user_day: ClassVar[int] = 10

    trigger_name: Identifier
    action: Identifier
    resolution: Identifier
    condition_count: int
    repaired: bool
    cooldown_seconds: int


class TodosSubscriptionFailed(ServerEvent):
    """A trigger subscription could not be registered on a tracked todo."""

    event: ClassVar[str] = "todos:subscription_failed"
    budget_per_user_day: ClassVar[int] = 10

    trigger_name: Identifier
    reason: SubscriptionFailureReason


class TodosTriggerFired(ServerEvent):
    """A subscribed trigger passed its conditions and cooldown and ran its action."""

    event: ClassVar[str] = "todos:trigger_fired"
    budget_per_user_day: ClassVar[int] = 50

    trigger_name: Identifier
    action: Identifier
    resolution: Identifier
    condition_count: int
    # The event landed inside a run window already claimed, so it rides that next run.
    coalesced: bool


class TodosRunResultDelivered(ServerEvent):
    """A tracked todo's run result reached, or failed to reach, the user; destination is where it was routed."""

    event: ClassVar[str] = "todos:run_result_delivered"
    # One per run, like trigger_fired: an hourly tracked todo alone delivers 12+ a day.
    budget_per_user_day: ClassVar[int] = 50

    outcome: Identifier
    delivered: bool
    trigger_type: Identifier
    recurring: bool
    platform: Identifier | None = None
    destination: ProactiveDestinationKind | None = None
    destination_basis: ProactiveDestinationBasis | None = None


class TodosChatOpened(ServerEvent):
    """A user opened a tracked todo's chat from the todo."""

    event: ClassVar[str] = "todos:chat_opened"
    budget_per_user_day: ClassVar[int] = 100

    todo_id: ObjectIdStr


class TodosInboxDeskProvisioned(ServerEvent):
    """The user's Inbox desk tracked todo exists and its first morning run is armed."""

    event: ClassVar[str] = "todos:inbox_desk_provisioned"
    # One desk per user: provisioning repeats only on a reconnect race the insert dedupes.
    budget_per_user_day: ClassVar[int] = 2


class ProjectsCreated(ServerEvent):
    """A user created a todo project."""

    event: ClassVar[str] = "projects:created"
    budget_per_user_day: ClassVar[int] = 50


class ProjectsUpdated(ServerEvent):
    """A user updated a todo project."""

    event: ClassVar[str] = "projects:updated"
    budget_per_user_day: ClassVar[int] = 50


class ProjectsDeleted(ServerEvent):
    """A user deleted a todo project."""

    event: ClassVar[str] = "projects:deleted"
    budget_per_user_day: ClassVar[int] = 50


class TodosViewChanged(WebEvent):
    """A user switched todo views in the sidebar; pure client navigation."""

    event: ClassVar[str] = "todos:view_changed"
    budget_per_user_day: ClassVar[int] = 50

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
