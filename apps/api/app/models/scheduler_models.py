"""
Base scheduler models for task scheduling system.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class ScheduledTaskStatus(str, Enum):
    """Base status enum for scheduled tasks."""

    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class BaseScheduledTask(BaseModel):
    """
    Base model for any scheduled task.

    Contains all common scheduling-related fields that any scheduled task should have.
    Domain-specific models should inherit from this and add their own fields.
    """

    id: Optional[str] = Field(None, alias="_id")
    user_id: str = Field(..., description="User ID who owns this task")
    repeat: Optional[str] = Field(
        None, description="Cron expression for recurring tasks"
    )
    scheduled_at: datetime = Field(..., description="Next scheduled execution time")
    status: ScheduledTaskStatus = Field(
        default=ScheduledTaskStatus.SCHEDULED, description="Current status"
    )
    occurrence_count: int = Field(
        default=0, description="Number of times this task has been executed"
    )
    max_occurrences: Optional[int] = Field(
        None, description="Maximum number of executions (optional)"
    )
    stop_after: Optional[datetime] = Field(
        None, description="Stop executing after this date (optional)"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp",
    )

    @field_validator("scheduled_at", "stop_after", "created_at", "updated_at")
    @classmethod
    def ensure_timezone_aware(cls, v):
        """Ensure datetime fields are timezone-aware (UTC if no timezone)."""
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v

    @field_serializer("scheduled_at", "stop_after", "created_at", "updated_at")
    def serialize_datetime(self, value: Optional[datetime]) -> Optional[str]:
        """Serialize datetime fields to ISO format strings."""
        if value is not None:
            return value.isoformat()
        return None

    model_config = ConfigDict(populate_by_name=True)


class ScheduleConfig(BaseModel):
    """Configuration for scheduling a task."""

    repeat: Optional[str] = Field(
        None, description="Cron expression for recurring tasks"
    )
    scheduled_at: Optional[datetime] = Field(
        None, description="When to first execute the task"
    )
    max_occurrences: Optional[int] = Field(
        None, description="Maximum number of executions"
    )
    stop_after: Optional[datetime] = Field(
        None, description="Stop executing after this date"
    )
    base_time: Optional[datetime] = Field(
        None, description="Base time for cron calculations"
    )

    @field_validator("max_occurrences")
    @classmethod
    def check_max_occurrences(cls, v):
        if v is not None and v <= 0:
            raise ValueError("max_occurrences must be greater than 0")
        return v

    @field_validator("scheduled_at", "stop_after", "base_time")
    @classmethod
    def ensure_timezone_aware(cls, v):
        """Ensure datetime fields are timezone-aware (UTC if no timezone)."""
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v

    @field_validator("repeat")
    @classmethod
    def check_repeat_cron(cls, v):
        if v is not None:
            from app.utils.cron_utils import validate_cron_expression

            if not validate_cron_expression(v):
                raise ValueError(f"Invalid cron expression: {v}")
        return v


class TaskExecutionResult(BaseModel):
    """Result of executing a scheduled task."""

    success: bool = Field(..., description="Whether the task executed successfully")
    message: Optional[str] = Field(None, description="Result message or error details")
    data: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional result data"
    )


class SchedulerTaskInfo(BaseModel):
    """Information about a task in the scheduler."""

    task_id: str = Field(..., description="Unique task identifier")
    task_type: str = Field(
        ..., description="Type of task (e.g., 'reminder', 'workflow')"
    )
    scheduled_at: datetime = Field(..., description="When the task is scheduled to run")
    status: ScheduledTaskStatus = Field(..., description="Current task status")
    user_id: str = Field(..., description="User who owns this task")
