from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class NotificationType(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"
    ARCHIVED = "archived"


class NotificationSourceEnum(str, Enum):
    AI_EMAIL_DRAFT = "ai_email_draft"
    AI_CALENDAR_EVENT = "ai_calendar_event"
    AI_TODO_SUGGESTION = "ai_todo_suggestion"
    AI_REMINDER = "ai_reminder"
    AI_TODO_ADDED = "ai_todo_added"
    EMAIL_TRIGGER = "email_trigger"
    BACKGROUND_JOB = "background_job"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    SYSTEM_WORKFLOWS_PROVISIONED = "system_workflows_provisioned"


class ActionType(str, Enum):
    REDIRECT = "redirect"
    API_CALL = "api_call"
    MODAL = "modal"


class ActionStyle(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DANGER = "danger"


class RedirectConfig(BaseModel):
    url: str
    open_in_new_tab: bool = True
    close_notification: bool = False


class ApiCallConfig(BaseModel):
    endpoint: str
    method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
    payload: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    success_message: str | None = None
    error_message: str | None = None
    is_internal: bool | None = False


class ModalConfig(BaseModel):
    component: str
    props: dict[str, Any] = Field(default_factory=dict)


class ActionConfig(BaseModel):
    redirect: RedirectConfig | None = None
    api_call: ApiCallConfig | None = None
    modal: ModalConfig | None = None

    @model_validator(mode="after")
    def validate_single_config(self):
        """Ensure only one action config is set"""
        configs = [self.redirect, self.api_call, self.modal]
        non_none_configs = [c for c in configs if c is not None]

        if len(non_none_configs) > 1:
            raise ValueError("Only one action config should be specified")
        return self


class NotificationAction(BaseModel):
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
    title: str
    body: str
    actions: list[NotificationAction] | None = None
    rich_content: dict[str, Any] | None = None


class ChannelConfig(BaseModel):
    channel_type: str  # 'inapp', 'telegram', 'discord'
    enabled: bool = True
    priority: int = 1  # 1 highest
    template: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class NotificationRequest(BaseModel):
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
    def validate_priority(cls, v):
        if not 1 <= v <= 5:
            raise ValueError("Priority must be between 1 and 5")
        return v


class ChannelDeliveryStatus(BaseModel):
    channel_type: str
    status: NotificationStatus
    delivered_at: datetime | None = None
    error_message: str | None = None
    retry_count: int = 0
    skipped: bool = False


class NotificationRecord(BaseModel):
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


class ActionResult(BaseModel):
    success: bool
    message: str | None = None
    data: dict[str, Any] | None = None
    next_actions: list[NotificationAction] | None = None
    update_notification: dict[str, Any] | None = None
    update_action: dict[str, Any] | None = None
    error_code: str | None = None


class BulkActions(str, Enum):
    MARK_READ = "mark_read"
    ARCHIVE = "archive"


class ChannelPreferences(BaseModel):
    """User notification channel preferences."""

    telegram: bool = True
    discord: bool = True
    whatsapp: bool = True


class ChannelPreferencesUpdate(BaseModel):
    """Request body for updating channel preferences."""

    telegram: bool | None = None
    discord: bool | None = None
    whatsapp: bool | None = None
