import re
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class CalendarPreferencesUpdateRequest(BaseModel):
    selected_calendars: List[str]


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


class EventLookupRequest(BaseModel):
    event_id: Optional[str] = Field(None, title="Event ID to lookup")
    calendar_id: Optional[str] = Field(None, title="Calendar ID containing the event")
    query: Optional[str] = Field(
        None,
        title="Query string to search for event if event_id/calendar_id not provided",
    )

    @model_validator(mode="after")
    def validate_lookup(self):
        event_id = self.event_id
        calendar_id = self.calendar_id
        query = self.query

        # If both event_id and calendar_id are provided, ignore query
        if event_id and calendar_id:
            self.query = None
            return self

        # If only one of event_id or calendar_id is provided, error
        if (event_id and not calendar_id) or (calendar_id and not event_id):
            raise ValueError("Both event_id and calendar_id must be provided together.")

        # If neither event_id/calendar_id nor query is provided, error
        if not query:
            raise ValueError(
                "Either both event_id and calendar_id, or query, must be provided."
            )

        return self


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


class CalendarEventToolRequest(BaseCalendarEvent):
    """Model for LLM tool input with time string and duration approach."""

    # Input fields for time specification
    time_str: Optional[str] = Field(
        None,
        title="Time string: either a relative offset like '+02:30' or an ISO 8601 time",
    )
    duration_minutes: Optional[int] = Field(
        30, title="Duration of the event in minutes, defaults to 30 minutes", ge=1
    )
    timezone_offset: Optional[str] = Field(
        None,
        title="Timezone offset in `(+|-)HH:MM` format. Only provide when user explicitly mentions a timezone.",
    )

    @field_validator("timezone_offset")
    @classmethod
    def validate_timezone_offset(cls, v):
        """Validate timezone offset format (+|-)HH:MM"""
        if v is not None:
            if not re.match(r"^[+-]\d{2}:\d{2}$", v):
                raise ValueError("Timezone offset must be in (+|-)HH:MM format")
        return v

    @model_validator(mode="after")
    def validate_event_times(self) -> "CalendarEventToolRequest":
        """
        Validate event data based on event type after model initialization.
        """
        if not self.is_all_day:
            # For timed events, time_str is required
            if not self.time_str:
                raise ValueError("time_str is required for timed events")

            # Validate the format of time_str
            if self.time_str.startswith("+"):
                # This is a relative time offset, validate the format
                if not re.match(r"^\+\d{2}:\d{2}$", self.time_str):
                    raise ValueError(
                        "Relative time offset must be in the format '+HH:MM'"
                    )
            else:
                # This is an absolute time, try to parse it
                try:
                    # Replace space with T if needed
                    time_str = (
                        self.time_str.replace(" ", "T")
                        if " " in self.time_str
                        else self.time_str
                    )
                    datetime.fromisoformat(time_str)
                except ValueError:
                    raise ValueError(
                        f"Invalid time format: {self.time_str}. Use ISO format (YYYY-MM-DDTHH:MM:SS) for absolute times."
                    )

        # For recurring events, ensure time_str is provided for non-all-day events
        if self.recurrence and not self.is_all_day and not self.time_str:
            raise ValueError("Recurring events must have time_str specified")

        return self

    @property
    def event_date(self) -> str:
        """
        Returns the date part for all-day events.
        For all-day events without time_str, returns today's date in YYYY-MM-DD format.
        """
        if self.is_all_day and not self.time_str:
            return datetime.now().strftime("%Y-%m-%d")
        elif self.time_str and not self.time_str.startswith("+"):
            # Extract date part from ISO datetime string
            return (
                self.time_str.split("T")[0] if "T" in self.time_str else self.time_str
            )

        return datetime.now().strftime("%Y-%m-%d")

    def _apply_timezone_offset(self, dt: datetime, offset_str: str) -> datetime:
        """Apply timezone offset to datetime object."""
        # Parse offset string (+|-)HH:MM
        sign = 1 if offset_str.startswith("+") else -1
        hours, minutes = map(int, offset_str[1:].split(":"))
        offset_seconds = sign * (hours * 3600 + minutes * 60)
        tz = timezone(timedelta(seconds=offset_seconds))
        return dt.replace(tzinfo=tz)

    def process_times(self, user_time: str) -> "EventCreateRequest":
        """
        Process time strings and calculate start/end times, converting to EventCreateRequest.

        Args:
            user_time: Current user time in ISO format for timezone reference

        Returns:
            EventCreateRequest with processed start/end times
        """
        # Extract user's timezone from user_time
        user_datetime = datetime.fromisoformat(user_time)
        user_timezone = user_datetime.tzinfo if user_datetime.tzinfo else timezone.utc

        # Skip processing for all-day events
        if self.is_all_day:
            # For all-day events, use the date without time component
            event_date = self.event_date

            # Return a new EventCreateRequest with start/end set to event_date
            return EventCreateRequest(
                summary=self.summary,
                description=self.description,
                is_all_day=True,
                start=event_date,
                end=event_date,
                calendar_id=self.calendar_id,
                recurrence=self.recurrence,
                timezone=None,
            )

        # Check if time_str is provided
        if not self.time_str:
            raise ValueError("time_str is required for timed events")

        # Process time based on format
        try:
            if self.time_str.startswith("+"):
                # Relative time offset (e.g., "+02:30")
                offset_hours, offset_minutes = map(int, self.time_str[1:].split(":"))
                offset_seconds = offset_hours * 3600 + offset_minutes * 60

                # Calculate the future time (from user's current time)
                start_time = user_datetime + timedelta(seconds=offset_seconds)

                # Calculate end time based on duration
                end_time = start_time + timedelta(minutes=self.duration_minutes or 30)

                # Return new EventCreateRequest with calculated times
                return EventCreateRequest(
                    summary=self.summary,
                    description=self.description,
                    is_all_day=False,
                    start=start_time.isoformat(),
                    end=end_time.isoformat(),
                    calendar_id=self.calendar_id,
                    recurrence=self.recurrence,
                    timezone=None,
                )

            else:
                # Absolute time (ISO format)
                time_str = (
                    self.time_str.replace(" ", "T")
                    if " " in self.time_str
                    else self.time_str
                )
                dt = datetime.fromisoformat(time_str)

                # Apply timezone if specified
                if self.timezone_offset:
                    # User explicitly provided timezone
                    start_time = self._apply_timezone_offset(dt, self.timezone_offset)
                else:
                    # Use user's timezone
                    start_time = dt.replace(tzinfo=user_timezone)

                # Calculate end time based on duration
                end_time = start_time + timedelta(minutes=self.duration_minutes or 30)

                # Return new EventCreateRequest with calculated times
                return EventCreateRequest(
                    summary=self.summary,
                    description=self.description,
                    is_all_day=False,
                    start=start_time.isoformat(),
                    end=end_time.isoformat(),
                    calendar_id=self.calendar_id,
                    recurrence=self.recurrence,
                    timezone=None,
                )

        except ValueError as e:
            raise ValueError(f"Invalid time format: {self.time_str}. Error: {e}")


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


class CalendarEventUpdateToolRequest(BaseModel):
    """Request model for calendar event updates with timezone handling."""

    event_lookup: EventLookupRequest = Field(
        ..., description="Event lookup information"
    )
    user_time: str = Field(..., description="User's current time for timezone handling")

    # Update fields
    summary: Optional[str] = Field(None, description="Updated event summary")
    description: Optional[str] = Field(None, description="Updated event description")
    start: Optional[str] = Field(None, description="Updated start time")
    end: Optional[str] = Field(None, description="Updated end time")
    is_all_day: Optional[bool] = Field(None, description="Updated all-day status")
    timezone_offset: Optional[str] = Field(
        None, description="Timezone offset in (+|-)HH:MM format"
    )
    recurrence: Optional[RecurrenceData] = Field(
        None, description="Updated recurrence pattern"
    )

    @field_validator("timezone_offset")
    @classmethod
    def validate_timezone_offset(cls, v):
        """Validate timezone offset format (+|-)HH:MM"""
        if v is not None:
            if not re.match(r"^[+-]\d{2}:\d{2}$", v):
                raise ValueError("Timezone offset must be in (+|-)HH:MM format")
        return v

    def _apply_timezone_offset(self, dt: datetime, offset_str: str) -> datetime:
        """Apply timezone offset to datetime object."""
        # Parse offset string (+|-)HH:MM
        sign = 1 if offset_str.startswith("+") else -1
        hours, minutes = map(int, offset_str[1:].split(":"))
        offset_seconds = sign * (hours * 3600 + minutes * 60)
        tz = timezone(timedelta(seconds=offset_seconds))
        return dt.replace(tzinfo=tz)

    def to_update_request(self) -> EventUpdateRequest:
        """Convert to EventUpdateRequest with processed times."""
        # Extract user's timezone from user_time
        user_datetime = datetime.fromisoformat(self.user_time)
        user_timezone = user_datetime.tzinfo if user_datetime.tzinfo else timezone.utc

        # Process start time if provided
        processed_start = None
        if self.start is not None:
            try:
                dt = datetime.fromisoformat(self.start.replace(" ", "T"))

                if self.timezone_offset:
                    processed_start_dt = self._apply_timezone_offset(
                        dt, self.timezone_offset
                    )
                else:
                    processed_start_dt = dt.replace(tzinfo=user_timezone)

                processed_start = processed_start_dt.isoformat()

            except ValueError as e:
                raise ValueError(f"Invalid start time format: {self.start}. Error: {e}")

        # Process end time if provided
        processed_end = None
        if self.end is not None:
            try:
                dt = datetime.fromisoformat(self.end.replace(" ", "T"))

                if self.timezone_offset:
                    processed_end_dt = self._apply_timezone_offset(
                        dt, self.timezone_offset
                    )
                else:
                    processed_end_dt = dt.replace(tzinfo=user_timezone)

                processed_end = processed_end_dt.isoformat()

            except ValueError as e:
                raise ValueError(f"Invalid end time format: {self.end}. Error: {e}")

        return EventUpdateRequest(
            event_id=self.event_lookup.event_id or "",
            calendar_id=self.event_lookup.calendar_id or "primary",
            summary=self.summary,
            description=self.description,
            start=processed_start,
            end=processed_end,
            is_all_day=self.is_all_day,
            timezone=None,
            timezone_offset=None,  # Processed times no longer need timezone_offset
            original_summary=None,
            recurrence=self.recurrence,
        )


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

    calendar_ids: Optional[List[str]] = Field(
        default=None,
        description="Calendar IDs to fetch from. If None, fetches from all user's selected calendars. Use ['primary'] for just the primary calendar.",
    )
    time_min: Optional[str] = Field(
        default=None,
        description="Start time filter (ISO format). Defaults to current time.",
    )
    time_max: Optional[str] = Field(
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
    count: Optional[int] = Field(
        default=None, description="Number of occurrences (don't use with until_date)"
    )
    until_date: Optional[str] = Field(
        default=None,
        description="End date for recurrence (YYYY-MM-DD) (don't use with count)",
    )
    by_day: Optional[List[str]] = Field(
        default=None,
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
        if self.count is not None and self.until_date is not None:
            raise ValueError("Cannot specify both 'count' and 'until_date'")
        return self
