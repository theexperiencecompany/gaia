import re
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class CalendarPreferencesUpdateRequest(BaseModel):
    selected_calendars: List[str]


class CalendarEventsQueryRequest(BaseModel):
    """Request model for querying calendar events via POST to avoid URL length limits."""

    selected_calendars: List[str] = Field(
        ..., description="List of calendar IDs to fetch events from"
    )
    start_date: Optional[str] = Field(
        None, description="Start date in YYYY-MM-DD format"
    )
    end_date: Optional[str] = Field(None, description="End date in YYYY-MM-DD format")
    fetch_all: bool = Field(
        True,
        description="Fetch ALL events in range (true) or limit per calendar (false)",
    )
    max_results: Optional[int] = Field(
        None,
        ge=1,
        le=250,
        description="Max events per calendar (only used if fetch_all=false)",
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v):
        """Validate date format is YYYY-MM-DD and date is valid."""
        if v is not None:
            date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
            if not date_pattern.match(v):
                raise ValueError(f"Invalid date format: {v}. Use YYYY-MM-DD format.")
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Invalid date: {v}")
        return v


class EventDeleteRequest(BaseModel):
    event_id: str = Field(..., title="Event ID to delete")
    calendar_id: str = Field("primary", title="Calendar ID containing the event")
    summary: Optional[str] = Field(None, title="Event summary for confirmation")


class BatchEventCreateRequest(BaseModel):
    events: List["EventCreateRequest"] = Field(..., title="List of events to create")


class BatchEventUpdateRequest(BaseModel):
    events: List["EventUpdateRequest"] = Field(..., title="List of events to update")


class BatchEventDeleteRequest(BaseModel):
    events: List[EventDeleteRequest] = Field(..., title="List of events to delete")


class RecurrenceRule(BaseModel):
    """
    Model representing a recurrence rule (RRULE) for a recurring event following RFC 5545.

    This model supports the core components needed to define recurring events in Google Calendar:
    - FREQ: Required frequency of repetition (daily, weekly, monthly, yearly)
    - INTERVAL: Optional interval between occurrences (default: 1)
    - COUNT: Optional number of occurrences
    - UNTIL: Optional end date (inclusive)
    - BYDAY: Optional days of week (e.g., for weekly events)
    - BYMONTHDAY: Optional days of month (e.g., for monthly events)
    - BYMONTH: Optional months of year (e.g., for yearly events)
    """

    frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "YEARLY"] = Field(
        ..., title="Frequency of repetition"
    )
    interval: Optional[int] = Field(1, title="Interval between occurrences", ge=1)
    count: Optional[int] = Field(None, title="Number of occurrences", ge=1)
    until: Optional[str] = Field(
        None, title="End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS±HH:MM)"
    )
    by_day: Optional[List[str]] = Field(
        None, title="Days of week (SU, MO, TU, WE, TH, FR, SA)"
    )
    by_month_day: Optional[List[int]] = Field(
        None,
        title="Days of month (1-31)",
    )
    by_month: Optional[List[int]] = Field(None, title="Months of year (1-12)")

    exclude_dates: Optional[List[str]] = Field(
        None, title="Dates to exclude (in YYYY-MM-DD format)"
    )
    include_dates: Optional[List[str]] = Field(
        None, title="Additional dates to include (in YYYY-MM-DD format)"
    )

    @field_validator("by_day")
    @classmethod
    def validate_by_day(cls, v):
        if v:
            valid_days = {"SU", "MO", "TU", "WE", "TH", "FR", "SA"}
            for day in v:
                if day not in valid_days:
                    raise ValueError(
                        f"Invalid day value: {day}. Must be one of {valid_days}"
                    )
        return v

    @field_validator("by_month_day")
    @classmethod
    def validate_by_month_day(cls, v):
        if v:
            for day in v:
                if day < 1 or day > 31:
                    raise ValueError(
                        f"Invalid day of month: {day}. Must be between 1 and 31"
                    )
        return v

    @field_validator("by_month")
    @classmethod
    def validate_by_month(cls, v):
        if v:
            for month in v:
                if month < 1 or month > 12:
                    raise ValueError(
                        f"Invalid month: {month}. Must be between 1 and 12"
                    )
        return v

    @model_validator(mode="after")
    def validate_recurrence(self) -> "RecurrenceRule":
        """
        Validate the recurrence rule based on frequency type
        """
        # Cannot specify both count and until
        if self.count is not None and self.until is not None:
            raise ValueError(
                "Cannot specify both 'count' and 'until' in a recurrence rule"
            )

        # Validate the until date format if provided
        if self.until:
            try:
                # Try to parse the date to validate it
                if "T" in self.until:  # ISO datetime format
                    datetime.fromisoformat(self.until.replace("Z", "+00:00"))
                else:  # Simple date format
                    datetime.fromisoformat(self.until)
            except ValueError:
                raise ValueError(
                    "Invalid 'until' date format. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS±HH:MM)"
                )

        # Specific validations based on frequency
        if self.frequency == "WEEKLY" and not self.by_day:
            # For weekly frequency, by_day should typically be specified
            pass  # This is just a recommendation, not an error

        if self.frequency == "MONTHLY" and self.by_day and self.by_month_day:
            raise ValueError(
                "Cannot specify both 'by_day' and 'by_month_day' for monthly recurrence"
            )

        return self

    def to_rrule_string(self) -> str:
        """
        Convert the RecurrenceRule object to an RFC 5545 RRULE string
        """
        components = [f"FREQ={self.frequency}"]

        if self.interval != 1:
            components.append(f"INTERVAL={self.interval}")

        if self.count is not None:
            components.append(f"COUNT={self.count}")

        if self.until is not None:
            # Format UNTIL value according to RFC 5545
            if "T" in self.until:  # Contains time component
                # Ensure it ends with Z for UTC
                until_value = self.until.replace("+00:00", "Z")
                if not until_value.endswith("Z"):
                    try:
                        dt = datetime.fromisoformat(self.until)
                        until_value = dt.strftime("%Y%m%dT%H%M%SZ")
                    except ValueError:
                        until_value = self.until
            else:  # Just a date
                try:
                    dt = datetime.fromisoformat(self.until)
                    until_value = dt.strftime("%Y%m%d")
                except ValueError:
                    until_value = self.until.replace("-", "")

            components.append(f"UNTIL={until_value}")

        if self.by_day:
            components.append(f"BYDAY={','.join(self.by_day)}")

        if self.by_month_day:
            components.append(f"BYMONTHDAY={','.join(map(str, self.by_month_day))}")

        if self.by_month:
            components.append(f"BYMONTH={','.join(map(str, self.by_month))}")

        return "RRULE:" + ";".join(components)

    @field_validator("exclude_dates", "include_dates")
    @classmethod
    def validate_dates(cls, v):
        if v:
            date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
            for date in v:
                if not date_pattern.match(date):
                    raise ValueError(
                        f"Invalid date format: {date}. Use YYYY-MM-DD format."
                    )
                try:
                    datetime.fromisoformat(date)
                except ValueError:
                    raise ValueError(f"Invalid date: {date}")
        return v

    model_config = {"extra": "forbid"}


class RecurrenceData(BaseModel):
    """
    Model representing the complete recurrence data for an event.

    This can include:
    - rrule: The main recurrence rule
    - exclude_dates: Specific dates to exclude from the recurrence pattern
    - include_dates: Additional specific dates to include in the pattern
    """

    rrule: RecurrenceRule = Field(..., title="Recurrence rule")

    def to_google_calendar_format(self) -> List[str]:
        """
        Convert the recurrence data to the format expected by Google Calendar API.

        Returns:
            List[str]: List of recurrence rules in RFC 5545 format
        """
        rules = [self.rrule.to_rrule_string()]

        if self.rrule.include_dates:
            # Format: "RDATE;VALUE=DATE:20150609,20150714"
            formatted_dates = ",".join(
                [date.replace("-", "") for date in self.rrule.include_dates]
            )
            rules.append(f"RDATE;VALUE=DATE:{formatted_dates}")

        if self.rrule.exclude_dates:
            # Format: "EXDATE;VALUE=DATE:20150610,20150715"
            formatted_dates = ",".join(
                [date.replace("-", "") for date in self.rrule.exclude_dates]
            )
            rules.append(f"EXDATE;VALUE=DATE:{formatted_dates}")

        rules.reverse()  # Reverse to match Google Calendar's order
        return rules

    model_config = {"extra": "forbid"}


class EventUpdateRequest(BaseModel):
    event_id: str = Field(..., title="Event ID to update")
    calendar_id: str = Field("primary", title="Calendar ID containing the event")
    summary: Optional[str] = Field(None, title="Updated event summary")
    description: Optional[str] = Field(None, title="Updated event description")
    start: Optional[str] = Field(None, title="Updated start time in ISO 8601 format")
    end: Optional[str] = Field(None, title="Updated end time in ISO 8601 format")
    is_all_day: Optional[bool] = Field(None, title="Updated all-day status")
    timezone: Optional[str] = Field(
        None, title="Timezone for the event (e.g., 'America/Los_Angeles', 'UTC')"
    )
    timezone_offset: Optional[str] = Field(
        None, title="Updated timezone offset in (+|-)HH:MM format"
    )
    original_summary: Optional[str] = Field(
        None, title="Original event summary for confirmation"
    )
    recurrence: Optional[RecurrenceData] = Field(
        None, title="Recurrence rules for recurring event"
    )


class BaseCalendarEvent(BaseModel):
    """Base model for calendar events with common fields shared across models."""

    summary: str = Field(..., title="Event Summary")
    description: str = Field("", title="Event Description")
    is_all_day: bool = Field(False, title="Is All Day Event")
    calendar_id: Optional[str] = Field(None, title="Calendar ID")
    recurrence: Optional[RecurrenceData] = Field(
        None, title="Recurrence rules for creating a recurring event"
    )

    model_config = {"extra": "ignore"}


class EventCreateRequest(BaseCalendarEvent):
    """Model for calendar event creation for service layer."""

    # Direct time fields for service operations
    start: str = Field(..., title="Start time in ISO format or date for all-day events")
    end: str = Field(..., title="End time in ISO format or date for all-day events")
    timezone: Optional[str] = Field(
        None, title="Timezone for the event (e.g., 'America/Los_Angeles', 'UTC')"
    )

    # Validate that start and end times are in ISO format or date format
    @field_validator("start", "end")
    @classmethod
    def validate_time_format(cls, v, info):
        field_name = info.field_name

        try:
            # Try to parse as ISO datetime
            datetime.fromisoformat(v)
        except ValueError:
            # If not ISO datetime, check if it's a valid date (YYYY-MM-DD)
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise ValueError(
                    f"{field_name} must be in ISO format (YYYY-MM-DDTHH:MM:SS) or date format (YYYY-MM-DD)"
                )

        return v

    @model_validator(mode="after")
    def validate_times(self) -> "EventCreateRequest":
        """Validate that start time is before end time for timed events."""
        if not self.is_all_day:
            try:
                start_time = datetime.fromisoformat(self.start)
                end_time = datetime.fromisoformat(self.end)

                if start_time >= end_time:
                    raise ValueError("Start time must be before end time")
            except ValueError as e:
                if "fromisoformat" not in str(e):
                    raise e
                # This means the format validation failed, which is handled by the field validator
                pass

        return self


class SingleEventInput(BaseModel):
    """Single event definition for creation."""

    summary: str = Field(..., description="Title of the event")
    start_datetime: str = Field(
        ...,
        description="Start time in ISO format (e.g., '2024-01-15T10:00:00'). Use user's timezone.",
    )
    duration_hours: float = Field(
        default=0, description="Duration hours (0-23)", ge=0, le=23
    )
    duration_minutes: float = Field(
        default=30, description="Duration minutes (0-59)", ge=0, le=59
    )
    calendar_id: str = Field(default="primary", description="Calendar ID")
    description: Optional[str] = Field(default=None, description="Event description")
    location: Optional[str] = Field(default=None, description="Event location")
    attendees: Optional[List[str]] = Field(
        default=None, description="List of attendee email addresses"
    )
    is_all_day: bool = Field(default=False, description="All-day event")


class CreateEventInput(BaseModel):
    """Input for creating one or more calendar events."""

    events: List[SingleEventInput] = Field(
        ...,
        description="List of events to create",
    )
    confirm_immediately: bool = Field(
        default=False,
        description="If True, create events immediately. If False (default), send to frontend for confirmation.",
    )


class ListCalendarsInput(BaseModel):
    short: bool = Field(
        default=True,
        description="Return only essential fields (id, summary, description, backgroundColor)",
    )


class FetchEventsInput(BaseModel):
    """Input for fetching events from one or more calendars."""

    calendar_ids: list[str] = Field(
        default_factory=list,
        description="Calendar IDs to fetch from. If empty, fetches from all user's selected calendars. Use ['primary'] for just the primary calendar.",
    )
    time_min: str | None = Field(
        default=None,
        description="Start time filter (ISO format). Defaults to current time.",
    )
    time_max: str | None = Field(
        default=None, description="End time filter (ISO format)"
    )
    max_results: int = Field(
        default=30, description="Maximum events to return (1-250)", ge=1, le=250
    )


class GetDaySummaryInput(BaseModel):
    """Input for getting a day's schedule summary."""

    date: Optional[str] = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d"),
        description="Date to get summary for (YYYY-MM-DD format). Defaults to today.",
    )


class FindEventInput(BaseModel):
    query: str = Field(..., description="Search query text")
    calendar_id: str = Field(default="primary", description="Calendar ID to search")
    time_min: Optional[str] = Field(
        default=None, description="Start time filter (ISO format)"
    )
    time_max: Optional[str] = Field(
        default=None, description="End time filter (ISO format)"
    )


class EventReference(BaseModel):
    """Reference to a specific event by ID and calendar."""

    event_id: str = Field(..., description="Event ID")
    calendar_id: str = Field(default="primary", description="Calendar ID")


class GetEventInput(BaseModel):
    """Input for getting one or more events by ID."""

    events: List[EventReference] = Field(
        ...,
        description="List of events to get (each with event_id and calendar_id)",
    )


class DeleteEventInput(BaseModel):
    """Input for deleting one or more events."""

    events: List[EventReference] = Field(
        ...,
        description="List of events to delete (each with event_id and calendar_id)",
    )
    send_updates: str = Field(
        default="all",
        description="Notify attendees: 'all', 'externalOnly', 'none'",
    )


class PatchEventInput(BaseModel):
    event_id: str = Field(..., description="Event ID to update")
    calendar_id: str = Field(default="primary", description="Calendar ID")
    summary: Optional[str] = Field(default=None, description="New title")
    description: Optional[str] = Field(default=None, description="New description")
    start_datetime: Optional[str] = Field(
        default=None, description="New start time (ISO format)"
    )
    end_datetime: Optional[str] = Field(
        default=None, description="New end time (ISO format)"
    )
    location: Optional[str] = Field(default=None, description="New location")
    attendees: Optional[List[str]] = Field(
        default=None, description="New attendees list"
    )
    send_updates: str = Field(default="all", description="Notify attendees")


class AddRecurrenceInput(BaseModel):
    event_id: str = Field(..., description="Event ID to add recurrence to")
    calendar_id: str = Field(default="primary", description="Calendar ID")
    frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "YEARLY"] = Field(
        ..., description="Recurrence frequency"
    )
    interval: int = Field(default=1, description="Interval between occurrences", ge=1)
    count: int = Field(
        default=0, description="Number of occurrences (don't use with until_date)"
    )
    until_date: str = Field(
        default="",
        description="End date for recurrence (YYYY-MM-DD) (don't use with count)",
    )
    by_day: list[str] = Field(
        default_factory=list,
        description="Days of week: 'SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'",
    )

    @field_validator("by_day")
    @classmethod
    def validate_by_day(cls, v):
        if v:
            valid_days = {"SU", "MO", "TU", "WE", "TH", "FR", "SA"}
            for day in v:
                if day not in valid_days:
                    raise ValueError(f"Invalid day: {day}. Must be one of {valid_days}")
        return v

    @model_validator(mode="after")
    def validate_recurrence(self):
        if self.count > 0 and self.until_date:
            raise ValueError("Cannot specify both 'count' and 'until_date'")
        return self
