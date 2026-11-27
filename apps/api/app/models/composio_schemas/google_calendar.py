"""
Google Calendar trigger payloads.

Reference: node_modules/@composio/core/generated/googlecalendar.ts
"""

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field


class GoogleCalendarEventCreatedPayload(BaseModel):
    """Payload for GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER."""

    calendar_id: str | None = Field(None, description="The calendar identifier")
    end_time: str | None = Field(None, description="Event end time in ISO format")
    event_id: str | None = Field(None, description="The unique identifier of the event")
    organizer_email: str | None = Field(None, description="Email of the event organizer")
    organizer_name: str | None = Field(None, description="Name of the event organizer")
    start_time: str | None = Field(None, description="Event start time in ISO format")
    summary: str | None = Field(None, description="Event title/summary")


class GoogleCalendarEventStartingSoonPayload(BaseModel):
    """Payload for GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER.

    Field set verified against Composio triggers_types API (2026-08).
    """

    attendees: list[dict[str, Any]] | None = Field(None, description="List of attendees")
    calendar_id: str | None = Field(None, description="The calendar identifier")
    countdown_window_minutes: int | None = Field(
        None, description="Countdown window used for this trigger"
    )
    creator_email: str | None = Field(None, description="Email of the event creator")
    description: str | None = Field(None, description="Event description")
    event_id: str | None = Field(None, description="The unique identifier of the event")
    hangout_link: str | None = Field(None, description="Google Meet link for the conference")
    html_link: str | None = Field(None, description="Link to the event in Google Calendar")
    location: str | None = Field(None, description="Event location")
    minutes_until_start: float | None = Field(
        None, description="Minutes remaining until event starts"
    )
    organizer_email: str | None = Field(None, description="Email of the event organizer")
    start_time: str | None = Field(None, description="Event start time in ISO format")
    start_timestamp: float | None = Field(
        None, description="Event start time as UNIX epoch timestamp (UTC)"
    )
    summary: str | None = Field(None, description="Event title")


class GoogleCalendarEventStartingSoonTriggerConfig(BaseModel):
    """Trigger config for GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER at the toolkit version oauth_config pins.

    That version (20260107_00) names the fields calendarId, minutes_before_start,
    countdown_window_minutes and include_all_day; any other name is dropped for its default
    (fire at 10, look ahead 60). minutes_before_start is when it fires; the look-ahead only
    bounds which events a poll evaluates, so it matches the lead.
    """

    model_config = ConfigDict(frozen=True)

    calendar_id: str = Field(
        serialization_alias="calendarId",
        validation_alias=AliasChoices("calendar_id", "calendarId"),
    )
    minutes_before_start: int = Field(ge=1, le=1440)
    include_all_day: bool

    @computed_field
    def countdown_window_minutes(self) -> int:
        """Look exactly as far ahead as the lead, so no event inside it goes unevaluated."""
        return self.minutes_before_start
