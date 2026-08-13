"""Unit tests for ``app.models.composio_schemas.google_calendar`` trigger payloads."""

from app.models.composio_schemas.google_calendar import (
    GoogleCalendarEventCreatedPayload,
    GoogleCalendarEventStartingSoonPayload,
)


def test_event_created_payload_parses_full_trigger() -> None:
    payload = GoogleCalendarEventCreatedPayload.model_validate(
        {
            "calendar_id": "cal-1",
            "end_time": "2026-01-01T10:00:00Z",
            "event_id": "evt-1",
            "organizer_email": "a@b.c",
            "organizer_name": "Ann",
            "start_time": "2026-01-01T09:00:00Z",
            "summary": "Standup",
        }
    )
    assert payload.event_id == "evt-1"
    assert payload.summary == "Standup"
    assert payload.organizer_email == "a@b.c"


def test_event_created_payload_allows_missing_optional_fields() -> None:
    payload = GoogleCalendarEventCreatedPayload.model_validate({})
    assert payload.calendar_id is None
    assert payload.event_id is None
    assert payload.summary is None


def test_event_starting_soon_parses_attendees_as_object_dicts() -> None:
    payload = GoogleCalendarEventStartingSoonPayload.model_validate(
        {
            "attendees": [{"email": "a@b.c", "response_status": "accepted"}],
            "countdown_window_minutes": 10,
            "organizer_self": False,
            "status": "confirmed",
            "summary": "Standup",
        }
    )
    assert payload.attendees == [{"email": "a@b.c", "response_status": "accepted"}]
    assert payload.countdown_window_minutes == 10
    assert payload.organizer_self is False
    assert payload.hangout_link is None


def test_event_starting_soon_coerces_numeric_countdown() -> None:
    payload = GoogleCalendarEventStartingSoonPayload.model_validate(
        {"countdown_window_minutes": "15"}
    )
    assert payload.countdown_window_minutes == 15
