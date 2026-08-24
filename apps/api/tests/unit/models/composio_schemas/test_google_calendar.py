"""Unit tests for app/models/composio_schemas/google_calendar.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.google_calendar import (
    GoogleCalendarEventCreatedPayload,
    GoogleCalendarEventStartingSoonPayload,
)


class TestGoogleCalendarEventCreatedPayload:
    def test_valid_minimal(self):
        m = GoogleCalendarEventCreatedPayload()
        assert m.event_id is None
        assert m.summary is None

    def test_valid_full(self):
        m = GoogleCalendarEventCreatedPayload(
            calendar_id="primary",
            end_time="2025-01-01T11:00:00Z",
            event_id="evt1",
            organizer_email="a@b.com",
            organizer_name="Alice",
            start_time="2025-01-01T10:00:00Z",
            summary="Standup",
        )
        assert m.event_id == "evt1"
        assert m.summary == "Standup"
        assert m.organizer_email == "a@b.com"

    def test_wrong_type_end_time(self):
        with pytest.raises(ValidationError):
            GoogleCalendarEventCreatedPayload(end_time=123)


class TestGoogleCalendarEventStartingSoonPayload:
    def test_valid_minimal(self):
        m = GoogleCalendarEventStartingSoonPayload()
        assert m.attendees is None
        assert m.countdown_window_minutes is None

    def test_valid_full(self):
        m = GoogleCalendarEventStartingSoonPayload(
            attendees=[{"email": "a@b.com"}],
            calendar_id="primary",
            countdown_window_minutes=10,
            creator_email="c@b.com",
            description="desc",
            event_id="evt1",
            hangout_link="https://meet.google.com/abc",
            html_link="https://calendar.google.com/event",
            location="Room 1",
            minutes_until_start=9.5,
            organizer_email="a@b.com",
            start_time="2025-01-01T10:00:00Z",
            start_timestamp=1735716000,
            summary="Standup",
        )
        assert m.countdown_window_minutes == 10
        assert m.minutes_until_start == 9.5
        assert m.start_timestamp == 1735716000

    def test_wrong_type_attendees(self):
        with pytest.raises(ValidationError):
            GoogleCalendarEventStartingSoonPayload(attendees=["not", "a", "dict"])

    def test_wrong_type_countdown(self):
        with pytest.raises(ValidationError):
            GoogleCalendarEventStartingSoonPayload(countdown_window_minutes="ten")


# ---------------------------------------------------------------------------
# google_docs
# ---------------------------------------------------------------------------
