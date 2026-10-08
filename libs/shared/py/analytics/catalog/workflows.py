"""Workflow events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier


class WorkflowCreated(ServerEvent):
    """A workflow was created, by the user or generated for a todo."""

    event: ClassVar[str] = "workflow:created"
    previous_names: ClassVar[tuple[str, ...]] = ("workflows:created",)

    workflow_id: Identifier | None = None
    trigger_type: Identifier | None = None
    steps_count: int | None = None
    generated_immediately: bool | None = None
    from_todo: bool | None = None
    is_todo_workflow: bool | None = None


class WorkflowExecuted(ServerEvent):
    """A workflow run was queued manually, or a background-triggered run completed."""

    event: ClassVar[str] = "workflow:executed"
    previous_names: ClassVar[tuple[str, ...]] = ("workflows:executed",)

    workflow_id: Identifier | None = None
    trigger_type: Identifier | None = None


class WorkflowActivated(ServerEvent):
    """A user activated a workflow."""

    event: ClassVar[str] = "workflow:activated"


class WorkflowDeactivated(ServerEvent):
    """A user deactivated a workflow."""

    event: ClassVar[str] = "workflow:deactivated"


class WorkflowPublished(ServerEvent):
    """A user published a workflow to the community."""

    event: ClassVar[str] = "workflow:published"
    previous_names: ClassVar[tuple[str, ...]] = ("workflows:published",)


class WorkflowUnpublished(ServerEvent):
    """A user unpublished a workflow."""

    event: ClassVar[str] = "workflow:unpublished"
    previous_names: ClassVar[tuple[str, ...]] = ("workflows:unpublished",)


class WorkflowUpdated(ServerEvent):
    """A user edited a workflow."""

    event: ClassVar[str] = "workflow:updated"


class WorkflowDeleted(ServerEvent):
    """A user deleted a workflow."""

    event: ClassVar[str] = "workflow:deleted"
    previous_names: ClassVar[tuple[str, ...]] = ("workflows:deleted",)


class WorkflowStepsRegenerated(ServerEvent):
    """A user asked for a workflow's steps to be regenerated."""

    event: ClassVar[str] = "workflow:steps_regenerated"
    previous_names: ClassVar[tuple[str, ...]] = ("workflows:steps_regenerated",)

    force_different_tools: bool
    steps_count: int


class WorkflowCardNavigate(WebEvent):
    """A user opened a workflow card's use-case page; client-side routing the server never sees."""

    event: ClassVar[str] = "workflow_card:navigate"

    slug: Identifier
    variant: Identifier
