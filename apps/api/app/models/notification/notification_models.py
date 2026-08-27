from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.repositories.base import UserScopedDocument


class NotificationType(str, Enum):
    """Severity/category of a notification, used for styling and filtering."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class NotificationStatus(str, Enum):
    """Lifecycle state of a notification record."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"
    ARCHIVED = "archived"


class NotificationSourceEnum(str, Enum):
    """Originating system or feature that produced the notification."""

    AI_EMAIL_DRAFT = "ai_email_draft"
    AI_CALENDAR_EVENT = "ai_calendar_event"
    AI_TODO_SUGGESTION = "ai_todo_suggestion"
    AI_REMINDER = "ai_reminder"
    AI_TODO_ADDED = "ai_todo_added"
    AI_AGENT = "ai_agent"
    EMAIL_TRIGGER = "email_trigger"
    BACKGROUND_JOB = "background_job"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    SYSTEM_WORKFLOWS_PROVISIONED = "system_workflows_provisioned"
    USAGE_LIMIT = "usage_limit"
    INTEGRATION_EXPIRED = "integration_expired"


class ActionType(str, Enum):
    """Kind of interaction a notification action performs when invoked."""

    REDIRECT = "redirect"
    API_CALL = "api_call"
    MODAL = "modal"


class ActionStyle(str, Enum):
    """Visual emphasis for a notification action button."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    DANGER = "danger"


class RedirectConfig(BaseModel):
    """Configuration for a redirect action that navigates the user to a URL."""

    url: str
    open_in_new_tab: bool = True
    close_notification: bool = False


class ApiCallConfig(BaseModel):
    """Configuration for an action that issues an HTTP request when invoked."""

    endpoint: str
    method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
    payload: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    success_message: str | None = None
    error_message: str | None = None
    is_internal: bool | None = False


class ModalConfig(BaseModel):
    """Configuration for an action that opens a frontend modal component."""

    component: str
    props: dict[str, Any] = Field(default_factory=dict)


class ActionConfig(BaseModel):
    """Container holding exactly one of the supported action configurations."""

    redirect: RedirectConfig | None = None
    api_call: ApiCallConfig | None = None
    modal: ModalConfig | None = None

    @model_validator(mode="after")
    def validate_single_config(self) -> "ActionConfig":
        """Ensure only one action config is set"""
        configs = [self.redirect, self.api_call, self.modal]
        non_none_configs = [c for c in configs if c is not None]

        if len(non_none_configs) > 1:
            raise ValueError("Only one action config should be specified")
        return self


class NotificationAction(BaseModel):
    """An interactive action (button) attached to a notification."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: ActionType
    label: str
    style: ActionStyle = ActionStyle.SECONDARY
    config: ActionConfig
    requires_confirmation: bool = False
    confirmation_message: str | None = None
    icon: str | None = None
    disabled: bool = False
    executed: bool = False
    executed_at: datetime | None = None

    def mark_as_executed(self) -> None:
        """Mark this action as executed"""
        self.executed = True
        self.executed_at = datetime.now(UTC)

    def is_executable(self) -> bool:
        """Check if this action can be executed"""
        if self.disabled:
            return False
        # For API calls, prevent double-execution
        if self.type == ActionType.API_CALL:
            return not self.executed
        # Redirect / Modal actions may be triggered multiple times
        return True


class NotificationContent(BaseModel):
    """Displayable payload of a notification: title, body, actions and rich data."""

    title: str
    body: str
    actions: list[NotificationAction] | None = None
    rich_content: dict[str, Any] | None = None


class ChannelConfig(BaseModel):
    """Per-channel delivery settings for a notification request."""

    channel_type: str  # 'inapp', 'telegram', 'discord'
    enabled: bool = True
    priority: int = 1  # 1 highest
    template: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class NotificationRequest(BaseModel):
    """Inbound request to send a notification to a user across channels."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    source: NotificationSourceEnum
    type: NotificationType = NotificationType.INFO
    priority: int = Field(default=3, ge=1, le=5)  # 1 highest
    channels: list[ChannelConfig] = Field(default_factory=list)
    content: NotificationContent
    metadata: dict[str, Any] = Field(default_factory=dict)
    scheduled_for: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("priority", mode="before")
    def validate_priority(cls, v: int) -> int:
        """Reject priorities outside the inclusive 1–5 range."""
        if not 1 <= v <= 5:
            raise ValueError("Priority must be between 1 and 5")
        return v


class ChannelDeliveryStatus(BaseModel):
    """Delivery outcome of a notification on a single channel."""

    channel_type: str
    status: NotificationStatus
    delivered_at: datetime | None = None
    error_message: str | None = None
    retry_count: int = 0
    skipped: bool = False


class NotificationRecord(UserScopedDocument):
    """Persisted notification with its original request and per-channel statuses.

    Identity is the UUID ``id`` (not Mongo's ``_id``); the notification repository
    sets ``identity_field = "id"``.
    """

    id: str
    user_id: str
    status: NotificationStatus = NotificationStatus.PENDING
    created_at: datetime
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    archived_at: datetime | None = None
    channels: list[ChannelDeliveryStatus] = Field(default_factory=list)
    original_request: NotificationRequest
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def mark_action_as_executed(self, action_id: str) -> bool:
        """Mark a specific action as executed"""
        if not self.original_request.content.actions:
            return False
        for action in self.original_request.content.actions:
            if action.id == action_id:
                action.mark_as_executed()
                self.updated_at = datetime.now(UTC)
                return True
        return False

    def get_action_by_id(self, action_id: str) -> NotificationAction | None:
        """Get a specific action by ID"""
        if not self.original_request.content.actions:
            return None
        for action in self.original_request.content.actions:
            if action.id == action_id:
                return action
        return None


class NotificationActionView(BaseModel):
    """A notification action as it appears on the wire (see ``NotificationView``)."""

    id: str
    type: ActionType
    label: str
    style: ActionStyle
    requires_confirmation: bool
    confirmation_message: str | None = None
    config: ActionConfig | None = None
    executed: bool
    executed_at: str | None = None
    disabled: bool


class NotificationContentView(BaseModel):
    """The ``content`` block of a ``NotificationView``."""

    title: str
    body: str
    actions: list[NotificationActionView] = Field(default_factory=list)


class NotificationChannelView(BaseModel):
    """One channel's delivery outcome as it appears on the wire.

    A narrower projection of ``ChannelDeliveryStatus``: ``retry_count`` is
    internal and deliberately not serialized.
    """

    channel_type: str
    status: NotificationStatus
    skipped: bool
    delivered_at: str | None = None
    error_message: str | None = None


class NotificationView(BaseModel):
    """A notification flattened for API/tool consumers.

    Distinct from ``NotificationRecord``: the record is the stored document (it
    nests the whole ``original_request``), while this is the flat shape the web
    and mobile clients actually read — ``content``/``source``/``type``/
    ``metadata`` are lifted out of the request, and the channel entries are
    projected. It mirrors ``NotificationRecord`` in the frontend's
    ``notificationTypes.ts``.

    Timestamps are ``str`` because the producer emits ISO strings and that is
    the published contract; parsing them into ``datetime`` here would re-emit
    them in Pydantic's own format.

    Built by ``NotificationOrchestrator._serialize_notification``, which is
    still the producer — this model is the named shape of what it returns.
    """

    id: str
    user_id: str
    status: NotificationStatus
    created_at: str
    delivered_at: str | None = None
    read_at: str | None = None
    content: NotificationContentView
    source: NotificationSourceEnum
    type: NotificationType
    metadata: dict[str, Any] = Field(default_factory=dict)
    channels: list[NotificationChannelView] = Field(default_factory=list)


class NotificationUpdate(BaseModel):
    """Typed status/timestamp fields for a notification update.

    Free-form patches (e.g. an action result's arbitrary field set) go through
    the repository's ``update_fields`` instead.
    """

    model_config = ConfigDict(extra="forbid")

    status: NotificationStatus | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    archived_at: datetime | None = None


class ActionResult(BaseModel):
    """Outcome of executing a notification action."""

    success: bool
    message: str | None = None
    data: dict[str, Any] | None = None
    next_actions: list[NotificationAction] | None = None
    update_notification: dict[str, Any] | None = None
    update_action: dict[str, Any] | None = None
    error_code: str | None = None


class BulkActions(str, Enum):
    """Bulk operations that can be applied to multiple notifications at once."""

    MARK_READ = "mark_read"
    ARCHIVE = "archive"


class ChannelPreferences(BaseModel):
    """User notification channel preferences."""

    telegram: bool = True
    discord: bool = True
    whatsapp: bool = True
    slack: bool = True


class ChannelPreferencesUpdate(BaseModel):
    """Request body for updating channel preferences."""

    telegram: bool | None = None
    discord: bool | None = None
    whatsapp: bool | None = None
    slack: bool | None = None
