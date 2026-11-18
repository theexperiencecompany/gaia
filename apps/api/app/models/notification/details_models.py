"""What a notification is about: one model per kind, told apart by the kind every one carries."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.notifications import NotificationKind
from app.models.brief_view_models import BriefEditionNotification, BriefNoteNotification


class TodoNotification(BaseModel):
    """A notification about one todo: its run's result, or what its health check found."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.TODO]
    todo_id: str


class TodoFailedNotification(BaseModel):
    """A scheduled todo that stopped after using up its attempts."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.TODO_FAILED]
    todo_id: str
    retry_count: int = Field(ge=1)


class TodoTriggerFiredNotification(BaseModel):
    """An event a todo's trigger subscription watches fired."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.TODO_TRIGGER_FIRED]
    todo_id: str
    subscription_id: str


class DormantTodosNotification(BaseModel):
    """The digest of the user's todos left idle."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.DORMANT_TODOS]
    todo_count: int = Field(ge=1)


class ReminderNotification(BaseModel):
    """A reminder that came due."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.REMINDER]
    reminder_id: str


class WorkflowCompletedNotification(BaseModel):
    """A finished workflow run; its result is in the conversation."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.WORKFLOW_COMPLETED]
    workflow_id: str
    conversation_id: str


class WorkflowFailedNotification(BaseModel):
    """A workflow run that errored or that a limit stopped."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    kind: Literal[NotificationKind.WORKFLOW_FAILED]
    workflow_id: str
    error_type: str | None = Field(
        default=None, description="The exception's class name, when the worker saw it."
    )


class WorkflowPausedNotification(BaseModel):
    """A workflow paused until the integrations it needs are connected."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.WORKFLOW_PAUSED]
    workflow_id: str
    missing_integrations: list[str] = Field(min_length=1)


class IntegrationExpiredNotification(BaseModel):
    """An integration whose connection expired, and how many workflows it paused."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.INTEGRATION_EXPIRED]
    integration_id: str
    paused_workflows: int = Field(ge=0)


class SystemWorkflowsProvisionedNotification(BaseModel):
    """Connecting an integration set up its system workflows."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.SYSTEM_WORKFLOWS_PROVISIONED]
    integration_display_name: str


class MemoryReadyNotification(BaseModel):
    """The user's memory was seeded from their past conversations."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.MEMORY_READY]


class GmailPersonalizedNotification(BaseModel):
    """GAIA personalised itself from the user's Gmail."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[NotificationKind.GMAIL_PERSONALIZED]


#: A notification's details, told apart by their kind.
NotificationDetails = Annotated[
    BriefEditionNotification
    | BriefNoteNotification
    | TodoNotification
    | TodoFailedNotification
    | TodoTriggerFiredNotification
    | DormantTodosNotification
    | ReminderNotification
    | WorkflowCompletedNotification
    | WorkflowFailedNotification
    | WorkflowPausedNotification
    | IntegrationExpiredNotification
    | SystemWorkflowsProvisionedNotification
    | MemoryReadyNotification
    | GmailPersonalizedNotification,
    Field(discriminator="kind"),
]
