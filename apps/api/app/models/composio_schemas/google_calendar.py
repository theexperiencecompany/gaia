"""
Google Calendar trigger payloads.

Reference: node_modules/@composio/core/generated/googlecalendar.ts
"""

from typing import Any

from pydantic import BaseModel, Field


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
    """Payload for GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER."""

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
    organizer_email: str | None = Field(None, description="Email of the event organizer")
    organizer_self: bool | None = Field(None, description="Whether the organizer is self")
    start_time: str | None = Field(None, description="Event start time in ISO format")
    status: str | None = Field(None, description="Event status")
    summary: str | None = Field(None, description="Event title")
    updated: str | None = Field(None, description="Event update time")
