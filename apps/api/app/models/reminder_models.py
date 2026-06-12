"""
Reminder models for task scheduling system.
"""

from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Union

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.models.scheduler_models import BaseScheduledTask, ScheduledTaskStatus
from app.utils.cron_utils import validate_cron_expression

# Use the base scheduler status directly
ReminderStatus = ScheduledTaskStatus


class AgentType(str, Enum):
    """Agent type handling the reminder task."""

    STATIC = "static"


class StaticReminderPayload(BaseModel):
    """Payload for STATIC agent reminders."""

    title: str = Field(
        ...,
        description=(
            "Notification title: short and human-readable, like a phone "
            "notification header (e.g. 'Drink water'). Shown directly to the user."
        ),
    )
    body: str = Field(
        ...,
        description=(
            "Notification body: write it as a natural, friendly message the user "
            "reads directly, the way you would text them (e.g. 'time to drink some "
            "water, stay hydrated!'). It is delivered as a push / WhatsApp / email "
            "notification across platforms, so use second person, no IDs, no "
            "internal jargon, no markdown."
        ),
    )


class ReminderModel(BaseScheduledTask):
    """Reminder document model for MongoDB (one-time or recurring)."""

    agent: AgentType = Field(..., description="Agent responsible for this reminder task")
    stop_after: datetime | None = Field(
        default=datetime.now(UTC) + timedelta(days=180),
        description="Stop executing after this date (optional), defaults to 6 months from now",
    )
    payload: Union[StaticReminderPayload, dict[str, Any]] = Field(
        ..., description="Task-specific data based on agent type"
    )


class CreateReminderRequest(BaseModel):
    """Request model for creating a new reminder."""

    agent: AgentType = Field(..., description="Agent handling the reminder task (static only)")
    repeat: str | None = Field(None, description="Cron expression for recurring tasks (optional)")
    scheduled_at: datetime | None = Field(
        None, description="First execution time (optional, defaults to None)"
    )
    max_occurrences: int | None = Field(None, description="Maximum number of executions (optional)")
    stop_after: datetime | None = Field(
        None, description="Stop executing after this date (optional)"
    )
    payload: StaticReminderPayload = Field(
        ..., description="Task-specific data for static reminder"
    )
    base_time: datetime | None = Field(
        None,
        description="Base time for handling time zones and scheduling (optional, defaults to None)",
    )

    @field_validator("repeat")
    @classmethod
    def check_repeat_cron(cls, v):
        from app.utils.cron_utils import validate_cron_expression

        if v is not None and not validate_cron_expression(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    @field_validator("scheduled_at")
    @classmethod
    def check_scheduled_at_future(cls, v):
        if v is not None:
            # Ensure timezone-aware datetime
            if v.tzinfo is None:
                v = v.replace(tzinfo=UTC)

            now = datetime.now(UTC)
            if v <= now:
                raise ValueError(
                    "scheduled_at must be in the future. The provided time "
                    f"({v.isoformat()}) has already passed; current time is "
                    f"{now.isoformat()} (UTC). For a relative reminder, pass "
                    "delay_seconds instead of computing a clock time."
                )
        return v

    @field_validator("max_occurrences")
    @classmethod
    def check_max_occurrences(cls, v):
        if v is not None and v <= 0:
            raise ValueError("max_occurrences must be greater than 0")
        return v

    @field_validator("stop_after")
    @classmethod
    def check_stop_after_future(cls, v):
        if v is not None:
            # Ensure timezone-aware datetime
            if v.tzinfo is None:
                v = v.replace(tzinfo=UTC)

            if v <= datetime.now(UTC):
                raise ValueError("stop_after must be in the future")
        return v

    @field_serializer("scheduled_at", "stop_after", "base_time", when_used="json")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        """ISO strings for JSON only; python mode keeps native datetimes so a
        model_dump() used to build a Mongo document never persists a string date."""
        if value is not None:
            return value.isoformat()
        return None


class CreateReminderToolRequest(BaseModel):
    """Request model for create_reminder_tool with timezone handling and validation."""

    agent: AgentType = Field(
        default=AgentType.STATIC,
        description="Agent handling the reminder task (static only)",
    )
    payload: StaticReminderPayload = Field(
        ..., description="Task-specific data for static reminder"
    )
    repeat: str | None = Field(None, description="Cron expression for recurring tasks (optional)")
    scheduled_at: str | None = Field(
        None,
        description="Date/time for when the reminder should run (YYYY-MM-DD HH:MM:SS format)",
    )
    timezone_offset: str | None = Field(
        None,
        description="Timezone offset in (+|-)HH:MM format. Only use if user explicitly mentions a timezone.",
    )
    max_occurrences: int | None = Field(None, description="Maximum number of executions (optional)")
    stop_after: str | None = Field(
        None,
        description="Date/time after which no more runs (YYYY-MM-DD HH:MM:SS format)",
    )
    stop_after_timezone_offset: str | None = Field(
        None,
        description="Timezone offset for stop_after in (+|-)HH:MM format. Only use if user explicitly mentions a timezone.",
    )
    delay_seconds: int | None = Field(
        None,
        description=(
            "Relative delay from NOW, in seconds, for one-off reminders phrased "
            "as 'in N minutes/hours/seconds' (e.g. 'remind me in 1 minute' -> 60). "
            "PREFER this for any relative request: the server computes the absolute "
            "time from the current time, so you never do timezone math. When set, "
            "scheduled_at / timezone_offset are ignored."
        ),
    )
    user_time: str = Field(..., description="User's current time for timezone handling")

    @field_validator("repeat")
    @classmethod
    def check_repeat_cron(cls, v):
        if v is not None and not validate_cron_expression(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    @field_validator("max_occurrences")
    @classmethod
    def check_max_occurrences(cls, v):
        if v is not None and v <= 0:
            raise ValueError("max_occurrences must be greater than 0")
        return v

    @field_validator("delay_seconds")
    @classmethod
    def check_delay_seconds(cls, v):
        if v is not None and v <= 0:
            raise ValueError("delay_seconds must be greater than 0")
        return v

    @field_validator("timezone_offset", "stop_after_timezone_offset")
    @classmethod
    def validate_timezone_offset(cls, v):
        """Validate timezone offset format (+|-)HH:MM"""
        if v is not None:
            import re

            if not re.match(r"^[+-]\d{2}:\d{2}$", v):
                raise ValueError("Timezone offset must be in (+|-)HH:MM format")
        return v

    def to_create_reminder_request(self) -> "CreateReminderRequest":
        """Convert to CreateReminderRequest with proper datetime handling."""
        # Extract user's timezone from user_time
        user_datetime = datetime.fromisoformat(self.user_time)
        user_timezone = user_datetime.tzinfo if user_datetime.tzinfo else UTC

        processed_scheduled_at = None
        if self.delay_seconds is not None:
            # Relative reminder ("in N minutes/seconds"): compute from the
            # authoritative current time so the LLM never does timezone math.
            # user_datetime is tz-aware, so adding a delta preserves the instant.
            processed_scheduled_at = user_datetime + timedelta(seconds=self.delay_seconds)
        elif self.scheduled_at:
            try:
                # Parse the datetime string
                dt = datetime.fromisoformat(self.scheduled_at.replace(" ", "T"))

                # Handle timezone based on the rules
                if self.timezone_offset:
                    # User explicitly provided timezone - create timezone from offset
                    processed_scheduled_at = self._apply_timezone_offset(dt, self.timezone_offset)
                else:
                    processed_scheduled_at = dt.replace(tzinfo=user_timezone)

            except ValueError as e:
                raise ValueError(
                    f"Invalid scheduled_at format: {self.scheduled_at}. Use YYYY-MM-DD HH:MM:SS format. Error: {e}"
                )

        processed_stop_after = None
        if self.stop_after:
            try:
                # Parse the datetime string
                dt = datetime.fromisoformat(self.stop_after.replace(" ", "T"))

                # Handle timezone based on the rules
                if self.stop_after_timezone_offset:
                    # User explicitly provided timezone - create timezone from offset
                    processed_stop_after = self._apply_timezone_offset(
                        dt, self.stop_after_timezone_offset
                    )
                else:
                    # Absolute time with no explicit timezone - use user's timezone
                    processed_stop_after = dt.replace(tzinfo=user_timezone)

            except ValueError as e:
                raise ValueError(
                    f"Invalid stop_after format: {self.stop_after}. Use YYYY-MM-DD HH:MM:SS format. Error: {e}"
                )

        return CreateReminderRequest(
            agent=self.agent,
            payload=self.payload,
            repeat=self.repeat,
            scheduled_at=processed_scheduled_at,
            max_occurrences=self.max_occurrences,
            stop_after=processed_stop_after,
            base_time=user_datetime,
        )

    def _apply_timezone_offset(self, dt: datetime, offset_str: str) -> datetime:
        """Apply timezone offset to datetime object."""
        # Parse offset string (+|-)HH:MM
        sign = 1 if offset_str.startswith("+") else -1
        hours, minutes = map(int, offset_str[1:].split(":"))
        offset_seconds = sign * (hours * 3600 + minutes * 60)
        tz = timezone(timedelta(seconds=offset_seconds))
        return dt.replace(tzinfo=tz)


class UpdateReminderRequest(BaseModel):
    """Request model for updating an existing reminder."""

    agent: AgentType | None = Field(None, description="Agent handling the reminder task (optional)")
    repeat: str | None = Field(None, description="Cron expression for recurring tasks")
    scheduled_at: datetime | None = Field(None, description="Next execution time")
    status: ReminderStatus | None = Field(None, description="Current status")
    max_occurrences: int | None = Field(None, description="Maximum number of executions")
    stop_after: datetime | None = Field(None, description="Stop executing after this date")
    payload: StaticReminderPayload | None = Field(None, description="Task-specific data (optional)")

    @field_validator("repeat")
    @classmethod
    def check_repeat_cron(cls, v):
        from app.utils.cron_utils import validate_cron_expression

        if v is not None and not validate_cron_expression(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    @field_validator("scheduled_at", "stop_after")
    @classmethod
    def ensure_timezone_aware(cls, v):
        """Ensure datetime fields are timezone-aware (UTC if no timezone)."""
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v

    @field_validator("max_occurrences")
    @classmethod
    def check_max_occurrences(cls, v):
        if v is not None and v <= 0:
            raise ValueError("max_occurrences must be greater than 0")
        return v

    @field_validator("stop_after")
    @classmethod
    def check_stop_after_future(cls, v):
        from datetime import datetime

        if v is not None:
            # Ensure timezone-aware datetime
            if v.tzinfo is None:
                v = v.replace(tzinfo=UTC)

            if v <= datetime.now(UTC):
                raise ValueError("stop_after must be in the future")
        return v

    @field_serializer("scheduled_at", "stop_after", when_used="json")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        """ISO strings for JSON only; python mode (the Mongo `$set` update path
        in update_reminder) keeps native datetimes so the persisted scheduled_at
        stays a BSON date the `$lte` recovery scan can match."""
        if value is not None:
            return value.isoformat()
        return None


class ReminderResponse(BaseModel):
    """Response model for reminder operations."""

    id: str = Field(..., description="Reminder ID")
    user_id: str = Field(..., description="User ID who owns this reminder")
    agent: AgentType = Field(..., description="Agent responsible for this reminder task")
    repeat: str | None = Field(None, description="Cron expression for recurring tasks")
    scheduled_at: datetime = Field(..., description="Next scheduled execution time")
    status: ReminderStatus = Field(..., description="Current status")
    occurrence_count: int = Field(
        ..., description="Number of times this reminder has been executed"
    )
    max_occurrences: int | None = Field(None, description="Maximum number of executions")
    stop_after: datetime | None = Field(None, description="Stop executing after this date")
    payload: Union[StaticReminderPayload, dict[str, Any]] = Field(
        ..., description="Task-specific data"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    @field_serializer("scheduled_at", "stop_after", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        """Serialize datetime fields to ISO format strings."""
        if value is not None:
            return value.isoformat()
        return None
