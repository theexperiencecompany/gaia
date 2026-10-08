"""Workflow events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier


class WorkflowCreated(ServerEvent):
    """A workflow was created, by the user or generated for a todo."""

    event: ClassVar[str] = "workflow:created"
    budget_per_user_day: ClassVar[int] = 200

    workflow_id: Identifier | None = None
    trigger_type: Identifier | None = None
    steps_count: int | None = None
    generated_immediately: bool | None = None
    from_todo: bool | None = None
    is_todo_workflow: bool | None = None


class WorkflowExecuted(ServerEvent):
    """A workflow run was queued manually, or a background-triggered run completed."""

    event: ClassVar[str] = "workflow:executed"
    budget_per_user_day: ClassVar[int] = 200

    workflow_id: Identifier | None = None
    trigger_type: Identifier | None = None


class WorkflowActivated(ServerEvent):
    """A user activated a workflow."""

    event: ClassVar[str] = "workflow:activated"
    budget_per_user_day: ClassVar[int] = 10


class WorkflowDeactivated(ServerEvent):
    """A user deactivated a workflow."""

    event: ClassVar[str] = "workflow:deactivated"
    budget_per_user_day: ClassVar[int] = 10


class WorkflowPublished(ServerEvent):
    """A user published a workflow to the community."""

    event: ClassVar[str] = "workflow:published"
    budget_per_user_day: ClassVar[int] = 10


class WorkflowUnpublished(ServerEvent):
    """A user unpublished a workflow."""

    event: ClassVar[str] = "workflow:unpublished"
    budget_per_user_day: ClassVar[int] = 50


class WorkflowUpdated(ServerEvent):
    """A user edited a workflow."""

    event: ClassVar[str] = "workflow:updated"
    budget_per_user_day: ClassVar[int] = 10


class WorkflowDeleted(ServerEvent):
    """A user deleted a workflow."""

    event: ClassVar[str] = "workflow:deleted"
    budget_per_user_day: ClassVar[int] = 50


class WorkflowStepsRegenerated(ServerEvent):
    """A user asked for a workflow's steps to be regenerated."""

    event: ClassVar[str] = "workflow:steps_regenerated"
    budget_per_user_day: ClassVar[int] = 10

    force_different_tools: bool
    steps_count: int


class WorkflowCardNavigate(WebEvent):
    """A user opened a workflow card's use-case page; client-side routing the server never sees."""

    event: ClassVar[str] = "workflow_card:navigate"
    budget_per_user_day: ClassVar[int] = 50

    slug: Identifier
    variant: Identifier


__all__ = [
    "WorkflowActivated",
    "WorkflowCardNavigate",
    "WorkflowCreated",
    "WorkflowDeactivated",
    "WorkflowDeleted",
    "WorkflowExecuted",
    "WorkflowPublished",
    "WorkflowStepsRegenerated",
    "WorkflowUnpublished",
    "WorkflowUpdated",
]
