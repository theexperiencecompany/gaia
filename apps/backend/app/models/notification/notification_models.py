from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
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


class ActionType(str, Enum):
    REDIRECT = "redirect"
    API_CALL = "api_call"
    WORKFLOW = "workflow"
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
    payload: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, str]] = None
    success_message: Optional[str] = None
    error_message: Optional[str] = None
    is_internal: Optional[bool] = False


class WorkflowConfig(BaseModel):
    workflow_id: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ModalConfig(BaseModel):
    component: str
    props: Dict[str, Any] = Field(default_factory=dict)


class ActionConfig(BaseModel):
    redirect: Optional[RedirectConfig] = None
    api_call: Optional[ApiCallConfig] = None
    workflow: Optional[WorkflowConfig] = None
    modal: Optional[ModalConfig] = None

    @model_validator(mode="after")
    def validate_single_config(self):
        """Ensure only one action config is set"""
        configs = [
            self.redirect,
            self.api_call,
            self.workflow,
            self.modal,
        ]
        non_none_configs = [c for c in configs if c is not None]

        if len(non_none_configs) > 1:
            raise ValueError("Only one action config should be specified")
        return self


class NotificationSource(str, Enum):
    """Enumeration of notification sources"""

    AI_EMAIL_DRAFT = "ai_email_draft"
    AI_CALENDAR_EVENT = "ai_calendar_event"
    AI_TODO_SUGGESTION = "ai_todo_suggestion"
    AI_REMINDER = "ai_reminder"
    AI_TODO_ADDED = "ai_todo_added"
    EMAIL_TRIGGER = "email_trigger"
    BACKGROUND_JOB = "background_job"


class NotificationAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: ActionType
    label: str
    style: ActionStyle = ActionStyle.SECONDARY
    config: ActionConfig
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    icon: Optional[str] = None
    disabled: bool = False
    executed: bool = False
    executed_at: Optional[datetime] = None

    def mark_as_executed(self) -> None:
        """Mark this action as executed"""
        self.executed = True
        self.executed_at = datetime.now(timezone.utc)

    def is_executable(self) -> bool:
        """Check if this action can be executed"""
        if self.disabled:
            return False

        # For API calls, check if already executed
        if self.type == ActionType.API_CALL:
            return not self.executed

        # Other action types may be executed multiple times
        return True


class NotificationContent(BaseModel):
    title: str
    body: str
    actions: Optional[List[NotificationAction]] = None
    rich_content: Optional[Dict[str, Any]] = None  # For HTML, markdown, etc.


class ChannelConfig(BaseModel):
    channel_type: str  # 'inapp', 'email', 'push', etc.
    enabled: bool = True
    priority: int = 1  # 1 highest
    template: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class NotificationRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    source: NotificationSourceEnum
    type: NotificationType = NotificationType.INFO
    priority: int = Field(default=3, ge=1, le=5)  # 1 highest
    channels: List[ChannelConfig]
    content: NotificationContent
    metadata: Dict[str, Any] = Field(default_factory=dict)
    scheduled_for: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("priority", mode="before")
    def validate_priority(cls, v):
        if not 1 <= v <= 5:
            raise ValueError("Priority must be between 1 and 5")
        return v


class ChannelDeliveryStatus(BaseModel):
    channel_type: str
    status: NotificationStatus
    delivered_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0


class NotificationRecord(BaseModel):
    id: str
    user_id: str
    status: NotificationStatus = NotificationStatus.PENDING
    created_at: datetime
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    snoozed_until: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    channels: List[ChannelDeliveryStatus] = Field(default_factory=list)
    original_request: NotificationRequest
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_as_read(self) -> None:
        """Mark notification as read"""
        self.status = NotificationStatus.READ
        self.read_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def archive(self) -> None:
        """Archive notification"""
        self.status = NotificationStatus.ARCHIVED
        self.archived_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def mark_action_as_executed(self, action_id: str) -> bool:
        """Mark a specific action as executed"""
        if not self.original_request.content.actions:
            return False

        for action in self.original_request.content.actions:
            if action.id == action_id:
                action.mark_as_executed()
                self.updated_at = datetime.now(timezone.utc)
                return True
        return False

    def get_action_by_id(self, action_id: str) -> Optional[NotificationAction]:
        """Get a specific action by ID"""
        if not self.original_request.content.actions:
            return None

        for action in self.original_request.content.actions:
            if action.id == action_id:
                return action
        return None


class ActionResult(BaseModel):
    success: bool
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    next_actions: Optional[List[NotificationAction]] = None
    update_notification: Optional[Dict[str, Any]] = None
    update_action: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None


class BulkActions(str, Enum):
    MARK_READ = "mark_read"
    ARCHIVE = "archive"
    DELETE = "delete"


class UserNotificationPreferences(BaseModel):
    user_id: str
    channel_preferences: Dict[str, Dict[str, Union[bool, int]]] = Field(
        default_factory=dict
    )
    # Format: {source: {channel_type: enabled, priority: int}}
    snooze_settings: Dict[str, Any] = Field(default_factory=dict)
    quiet_hours: Optional[Dict[str, str]] = None  # {'start': '22:00', 'end': '08:00'}
    max_notifications_per_hour: int = 50
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_channel_enabled(
        self, source: NotificationSourceEnum, channel_type: str
    ) -> bool:
        """Check if a channel is enabled for a source"""
        return bool(self.channel_preferences.get(source, {}).get(channel_type, True))

    def is_in_quiet_hours(self) -> bool:
        """Check if current time is in quiet hours"""
        if not self.quiet_hours:
            return False

        now = datetime.now().time()
        start = datetime.strptime(self.quiet_hours["start"], "%H:%M").time()
        end = datetime.strptime(self.quiet_hours["end"], "%H:%M").time()

        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end
