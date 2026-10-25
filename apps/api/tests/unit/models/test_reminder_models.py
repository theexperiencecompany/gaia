"""Unit tests for reminder Pydantic models."""

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
import pytest
import time_machine

from app.models.reminder_models import (
    CreateReminderRequest,
    CreateReminderToolRequest,
    StaticReminderPayload,
    UpdateReminderRequest,
)

# ---------------------------------------------------------------------------
# ReminderModel
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CreateReminderRequest
# ---------------------------------------------------------------------------


class TestCreateReminderRequest:
    def _future_dt(self, hours: int = 1) -> datetime:
        return datetime.now(UTC) + timedelta(hours=hours)

    def test_scheduled_at_in_past_raises(self):
        past = datetime.now(UTC) - timedelta(hours=1)
        with pytest.raises(ValidationError, match="must be in the future"):
            CreateReminderRequest(
                agent="static",
                payload=StaticReminderPayload(title="T", body="B"),
                scheduled_at=past,
            )

    def test_invalid_cron_repeat(self):
        with pytest.raises(ValidationError, match="Use 5 fields: minute hour day month weekday."):
            CreateReminderRequest(
                agent="static",
                payload=StaticReminderPayload(title="T", body="B"),
                repeat="bad-cron",
            )

    @pytest.mark.parametrize("val", [0, -1, -100])
    def test_max_occurrences_invalid(self, val):
        with pytest.raises(ValidationError, match="max_occurrences must be greater"):
            CreateReminderRequest(
                agent="static",
                payload=StaticReminderPayload(title="T", body="B"),
                max_occurrences=val,
            )

    def test_stop_after_in_past_raises(self):
        past = datetime.now(UTC) - timedelta(hours=1)
        with pytest.raises(ValidationError, match="stop_after must be in the future"):
            CreateReminderRequest(
                agent="static",
                payload=StaticReminderPayload(title="T", body="B"),
                stop_after=past,
            )


# ---------------------------------------------------------------------------
# CreateReminderToolRequest
# ---------------------------------------------------------------------------


class TestCreateReminderToolRequest:
    def _base_data(self, **overrides) -> dict:
        data: dict[str, Any] = {
            "payload": {"title": "Reminder", "body": "Don't forget"},
            "home_timezone": "Asia/Kolkata",
        }
        data.update(overrides)
        return data

    def test_invalid_cron_repeat(self):
        with pytest.raises(ValidationError, match="Use 5 fields: minute hour day month weekday."):
            CreateReminderToolRequest(**self._base_data(repeat="bad-cron"))

    @pytest.mark.parametrize("val", [0, -1])
    def test_max_occurrences_invalid(self, val):
        with pytest.raises(ValidationError, match="max_occurrences must be greater"):
            CreateReminderToolRequest(**self._base_data(max_occurrences=val))

    @pytest.mark.parametrize("offset", ["5:30", "UTC", "+5", "05:30", "abc"])
    def test_invalid_timezone_offsets(self, offset):
        with pytest.raises(ValidationError, match="Timezone offset must be"):
            CreateReminderToolRequest(**self._base_data(timezone_offset=offset))

    @pytest.mark.parametrize("offset", ["5:30", "UTC"])
    def test_invalid_stop_after_timezone_offsets(self, offset):
        with pytest.raises(ValidationError, match="Timezone offset must be"):
            CreateReminderToolRequest(**self._base_data(stop_after_timezone_offset=offset))


# ---------------------------------------------------------------------------
# CreateReminderToolRequest.to_create_reminder_request
# ---------------------------------------------------------------------------


class TestCreateReminderToolRequestConversion:
    def _base_data(self, **overrides) -> dict:
        data: dict[str, Any] = {
            "payload": {"title": "Reminder", "body": "Don't forget"},
            "home_timezone": "Asia/Kolkata",
        }
        data.update(overrides)
        return data

    def test_basic_conversion_no_schedule(self):
        """The agent's path passes stop_after=None explicitly; it still gets the six-month cutoff."""
        now = datetime.now(UTC)
        with time_machine.travel(now, tick=False):
            result = CreateReminderToolRequest(**self._base_data()).to_create_reminder_request()
        assert isinstance(result, CreateReminderRequest)
        assert result.scheduled_at is None
        assert result.stop_after == now + timedelta(days=180)

    def test_source_conversation_id_is_threaded_through(self):
        # The originating chat captured at the tool boundary must survive the
        # conversion to the service request, or the fire-time delivery has no
        # chat to deliver back into.
        m = CreateReminderToolRequest(**self._base_data(source_conversation_id="conv-99"))
        result = m.to_create_reminder_request()
        assert result.source_conversation_id == "conv-99"

    def test_conversion_with_scheduled_at_home_tz(self):
        m = CreateReminderToolRequest(**self._base_data(scheduled_at="2030-06-15 09:00:00"))
        result = m.to_create_reminder_request()
        assert result.scheduled_at is not None
        assert result.scheduled_at.tzinfo is not None
        # No explicit offset -> interpreted in the home zone (Asia/Kolkata, +05:30).
        assert result.scheduled_at.utcoffset() == timedelta(hours=5, minutes=30)

    def test_conversion_with_explicit_tz_offset(self):
        m = CreateReminderToolRequest(
            **self._base_data(
                scheduled_at="2030-06-15 09:00:00",
                timezone_offset="-08:00",
            )
        )
        result = m.to_create_reminder_request()
        assert result.scheduled_at is not None
        offset = result.scheduled_at.utcoffset()
        assert offset == timedelta(hours=-8)

    def test_conversion_with_stop_after_home_tz(self):
        m = CreateReminderToolRequest(**self._base_data(stop_after="2030-12-31 23:59:59"))
        result = m.to_create_reminder_request()
        assert result.stop_after is not None
        assert result.stop_after.tzinfo is not None
        # No explicit offset -> interpreted in the home zone (Asia/Kolkata, +05:30).
        assert result.stop_after.utcoffset() == timedelta(hours=5, minutes=30)

    def test_conversion_with_stop_after_explicit_tz(self):
        m = CreateReminderToolRequest(
            **self._base_data(
                stop_after="2030-12-31 23:59:59",
                stop_after_timezone_offset="+03:00",
            )
        )
        result = m.to_create_reminder_request()
        offset = result.stop_after.utcoffset()
        assert offset == timedelta(hours=3)

    def test_conversion_invalid_scheduled_at_format(self):
        m = CreateReminderToolRequest(**self._base_data(scheduled_at="not-a-datetime"))
        with pytest.raises(ValueError, match="Invalid scheduled_at format"):
            m.to_create_reminder_request()

    def test_conversion_invalid_stop_after_format(self):
        m = CreateReminderToolRequest(**self._base_data(stop_after="not-a-datetime"))
        with pytest.raises(ValueError, match="Invalid stop_after format"):
            m.to_create_reminder_request()

    def test_conversion_no_home_timezone_utc_fallback(self):
        """When no home_timezone is provided, absolute clock times fall back to UTC."""
        m = CreateReminderToolRequest(
            payload=StaticReminderPayload(title="T", body="B"),
            scheduled_at="2030-06-15 09:00:00",
        )
        result = m.to_create_reminder_request()
        assert result.scheduled_at is not None
        assert result.scheduled_at.tzinfo == UTC

    def test_conversion_delay_seconds_uses_server_now(self):
        """A relative delay computes now (server) + delay_seconds, tz-aware in the future."""
        before = datetime.now(UTC)
        m = CreateReminderToolRequest(**self._base_data(delay_seconds=60))
        result = m.to_create_reminder_request()
        after = datetime.now(UTC)

        assert result.scheduled_at is not None
        assert result.scheduled_at.tzinfo is not None
        # ~now + 60s, allowing for the elapsed wall-clock during the call.
        assert (
            before + timedelta(seconds=60) <= result.scheduled_at <= after + timedelta(seconds=60)
        )


# ---------------------------------------------------------------------------
# UpdateReminderRequest
# ---------------------------------------------------------------------------


class TestUpdateReminderRequest:
    def test_invalid_cron_repeat(self):
        with pytest.raises(ValidationError, match="Use 5 fields: minute hour day month weekday."):
            UpdateReminderRequest(repeat="bad-cron")

    @pytest.mark.parametrize("val", [0, -1])
    def test_max_occurrences_invalid(self, val):
        with pytest.raises(ValidationError, match="max_occurrences must be greater"):
            UpdateReminderRequest(max_occurrences=val)

    def test_stop_after_in_past_raises(self):
        past = datetime.now(UTC) - timedelta(hours=1)
        with pytest.raises(ValidationError, match="stop_after must be in the future"):
            UpdateReminderRequest(stop_after=past)

    def test_naive_stop_after_becomes_utc(self):
        future_naive = datetime(2030, 6, 15, 12, 0, 0)
        m = UpdateReminderRequest(stop_after=future_naive)
        assert m.stop_after.tzinfo is not None
