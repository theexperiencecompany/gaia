"""
Base scheduler models for task scheduling system.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.utils.schedule import RecurringSchedule


class ScheduledTaskStatus(str, Enum):
    """Base status enum for scheduled tasks."""

    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class DeactivationReason(str, Enum):
    """Why the system paused a reminder or deactivated a workflow.

    An automatic resume only touches tasks carrying the reason it owns, so a task
    the user switched off themselves (no reason) is never silently re-enabled.
    """

    USER_DORMANT = "user_dormant"
    INTEGRATION_EXPIRED = "integration_expired"
    SUBSCRIPTION_LAPSED = "subscription_lapsed"
    #: Set only when a run actually tries and finds the integration missing —
    #: unlike INTEGRATION_EXPIRED (a live connection dying, via Composio
    #: webhook). Not predicted from declared steps at authoring time.
    INTEGRATION_NEVER_CONNECTED = "integration_never_connected"
    #: A stored schedule that breaks the recurring-schedule rule; only the user can fix it.
    INVALID_SCHEDULE = "invalid_schedule"


class TaskOutcome(str, Enum):
    """What one fire of a scheduled task came to."""

    EXECUTED = "executed"
    FAILED = "failed"
    ENTITLEMENT_BLOCKED = "entitlement_blocked"


class BaseScheduledTask(BaseModel):
    """Base model for any scheduled task; domain models inherit and add their own fields."""

    id: str | None = Field(None, alias="_id")
    user_id: str = Field(..., description="User ID who owns this task")
    repeat: str | None = Field(None, description="Cron expression for recurring tasks")
    scheduled_at: datetime | None = Field(
        default=None,
        description="Next scheduled execution time; None when the task has no schedule "
        "(e.g. a manual/integration workflow). A null value never matches the due-scan.",
    )
    status: ScheduledTaskStatus = Field(
        default=ScheduledTaskStatus.SCHEDULED, description="Current status"
    )
    occurrence_count: int = Field(
        default=0, description="Number of times this task has been executed"
    )
    max_occurrences: int | None = Field(None, description="Maximum number of executions (optional)")
    stop_after: datetime | None = Field(
        None, description="Stop executing after this date (optional)"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp",
    )

    @field_validator("scheduled_at", "stop_after", "created_at", "updated_at")
    @classmethod
    def ensure_timezone_aware(cls, v: datetime | None) -> datetime | None:
        """Ensure datetime fields are timezone-aware (UTC if no timezone)."""
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v

    @field_serializer("scheduled_at", "stop_after", when_used="json")
    def serialize_schedule_datetime(self, value: datetime | None) -> str | None:
        """ISO strings for JSON only; python mode (Mongo writes) keeps native
        datetimes so the scheduler's `scheduled_at: {"$lte": now}` scan matches."""
        if value is not None:
            return value.isoformat()
        return None

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_audit_datetime(self, value: datetime | None) -> str | None:
        """ISO strings for JSON only; python mode (Mongo writes) keeps native
        datetimes so these match the same type as status-update/migration writes
        and sort correctly alongside them."""
        if value is not None:
            return value.isoformat()
        return None

    model_config = ConfigDict(populate_by_name=True)


class ScheduleConfig(BaseModel):
    """Configuration for scheduling a task."""

    repeat: RecurringSchedule | None = Field(
        None, description="Cron expression for recurring tasks"
    )
    scheduled_at: datetime | None = Field(None, description="When to first execute the task")
    max_occurrences: int | None = Field(None, description="Maximum number of executions")
    stop_after: datetime | None = Field(None, description="Stop executing after this date")

    @field_validator("max_occurrences")
    @classmethod
    def check_max_occurrences(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("max_occurrences must be greater than 0")
        return v

    @field_validator("scheduled_at", "stop_after")
    @classmethod
    def ensure_timezone_aware(cls, v: datetime | None) -> datetime | None:
        """Ensure datetime fields are timezone-aware (UTC if no timezone)."""
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v


class TaskExecutionResult(BaseModel):
    """Result of executing a scheduled task."""

    outcome: TaskOutcome = Field(..., description="What the fire came to")
    message: str | None = Field(None, description="Result message or error details")
    data: dict[str, Any] | None = Field(default=None, description="Additional result data")

    @property
    def success(self) -> bool:
        """Whether the task actually ran to completion."""
        return self.outcome is TaskOutcome.EXECUTED


class _Unset:
    """Sentinel for a TaskRearm field that was not provided — distinct from an
    explicit None, which the recovery scan legitimately writes (a reaped
    non-recurring workflow clears its scheduled_at)."""


UNSET = _Unset()


@dataclass(slots=True, frozen=True)
class TaskRearm:
    """The scheduler's re-arm fields that ride along with a status write.

    scheduled_at/next_run (a workflow's trigger_config.next_run) default to
    UNSET because None is a meaningful value the recovery scan writes: an
    omitted field is left untouched, an explicit None clears it.
    """

    scheduled_at: datetime | _Unset | None = UNSET
    occurrence_count: int | None = None
    repeat: str | None = None
    next_run: datetime | _Unset | None = UNSET
