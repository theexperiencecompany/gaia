"""
Google Calendar trigger payloads.

Reference: node_modules/@composio/core/generated/googlecalendar.ts
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GoogleCalendarEventCreatedPayload(BaseModel):
    """Payload for GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER."""

    calendar_id: Optional[str] = Field(None, description="The calendar identifier")
    end_time: Optional[str] = Field(None, description="Event end time in ISO format")
    event_id: Optional[str] = Field(
        None, description="The unique identifier of the event"
    )
    organizer_email: Optional[str] = Field(
        None, description="Email of the event organizer"
    )
    organizer_name: Optional[str] = Field(
        None, description="Name of the event organizer"
    )
    start_time: Optional[str] = Field(
        None, description="Event start time in ISO format"
    )
    summary: Optional[str] = Field(None, description="Event title/summary")


class GoogleCalendarEventStartingSoonPayload(BaseModel):
    """Payload for GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER."""

    attendees: Optional[List[Dict[str, Any]]] = Field(
        None, description="List of attendees"
    )
    calendar_id: Optional[str] = Field(None, description="The calendar identifier")
    countdown_window_minutes: Optional[int] = Field(
        None, description="Countdown window used for this trigger"
    )
    creator_email: Optional[str] = Field(None, description="Email of the event creator")
    description: Optional[str] = Field(None, description="Event description")
    event_id: Optional[str] = Field(
        None, description="The unique identifier of the event"
    )
    hangout_link: Optional[str] = Field(
        None, description="Google Meet link for the conference"
    )
    html_link: Optional[str] = Field(
        None, description="Link to the event in Google Calendar"
    )
    location: Optional[str] = Field(None, description="Event location")
    organizer_email: Optional[str] = Field(
        None, description="Email of the event organizer"
    )
    organizer_self: Optional[bool] = Field(
        None, description="Whether the organizer is self"
    )
    start_time: Optional[str] = Field(
        None, description="Event start time in ISO format"
    )
    status: Optional[str] = Field(None, description="Event status")
    summary: Optional[str] = Field(None, description="Event title")
    updated: Optional[str] = Field(None, description="Event update time")
