"""Unit tests for reminder Pydantic models."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from app.models.reminder_models import (
    AgentType,
    CreateReminderRequest,
    CreateReminderToolRequest,
    ReminderModel,
    ReminderProcessingAgentResult,
    ReminderResponse,
    ReminderStatus,
    StaticReminderPayload,
    UpdateReminderRequest,
)
from app.models.scheduler_models import ScheduledTaskStatus


# ---------------------------------------------------------------------------
# AgentType enum
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAgentType:
    def test_static_value(self):
        assert AgentType.STATIC == "static"
        assert AgentType.STATIC.value == "static"

    def test_is_str_enum(self):
        assert isinstance(AgentType.STATIC, str)


# ---------------------------------------------------------------------------
# ReminderStatus alias
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestReminderStatus:
    def test_alias_is_scheduled_task_status(self):
        assert ReminderStatus is ScheduledTaskStatus

    @pytest.mark.parametrize(
        "status",
        ["scheduled", "executing", "completed", "failed", "cancelled", "paused"],
    )
    def test_all_values(self, status):
        assert ReminderStatus(status).value == status


# ---------------------------------------------------------------------------
# StaticReminderPayload
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestStaticReminderPayload:
    def test_valid(self):
        m = StaticReminderPayload(title="Title", body="Body text")
        assert m.title == "Title"
        assert m.body == "Body text"

    def test_missing_title(self):
        with pytest.raises(ValidationError):
            StaticReminderPayload(body="Body")

    def test_missing_body(self):
        with pytest.raises(ValidationError):
            StaticReminderPayload(title="Title")

    def test_missing_both(self):
        with pytest.raises(ValidationError):
            StaticReminderPayload()


# ---------------------------------------------------------------------------
# ReminderModel
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestReminderModel:
    def _base_data(self, **overrides) -> dict:
        data: Dict[str, Any] = {
            "user_id": "user1",
            "agent": "static",
            "scheduled_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "payload": {"title": "Test", "body": "Body"},
        }
        data.update(overrides)
        return data

    def test_valid_minimal(self):
        m = ReminderModel(**self._base_data())
        assert m.user_id == "user1"
        assert m.agent == AgentType.STATIC
        assert m.occurrence_count == 0
        assert m.status == ScheduledTaskStatus.SCHEDULED
        assert m.stop_after is not None  # default is 6 months from now

    def test_payload_as_static_reminder(self):
        m = ReminderModel(**self._base_data())
        assert m.payload.title == "Test"  # type: ignore[union-attr]

    def test_payload_as_dict(self):
        m = ReminderModel(**self._base_data(payload={"custom_key": "custom_value"}))
        assert isinstance(m.payload, dict)
        assert m.payload["custom_key"] == "custom_value"

    def test_naive_scheduled_at_becomes_utc(self):
        naive_dt = datetime(2030, 1, 1, 12, 0, 0)
        m = ReminderModel(**self._base_data(scheduled_at=naive_dt))
        assert m.scheduled_at.tzinfo is not None

    def test_id_from_alias(self):
        m = ReminderModel(**self._base_data(_id="rem123"))
        assert m.id == "rem123"


# ---------------------------------------------------------------------------
# CreateReminderRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCreateReminderRequest:
    def _future_dt(self, hours: int = 1) -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=hours)

    def test_valid_minimal(self):
        m = CreateReminderRequest(
            agent="static",
            payload=StaticReminderPayload(title="T", body="B"),
        )
        assert m.agent == AgentType.STATIC
        assert m.repeat is None
        assert m.scheduled_at is None

    def test_valid_with_scheduled_at(self):
        future = self._future_dt()
        m = CreateReminderRequest(
            agent="static",
            payload=StaticReminderPayload(title="T", body="B"),
            scheduled_at=future,
        )
        assert m.scheduled_at is not None

    def test_scheduled_at_in_past_raises(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with pytest.raises(ValidationError, match="must be in the future"):
            CreateReminderRequest(
                agent="static",
                payload=StaticReminderPayload(title="T", body="B"),
                scheduled_at=past,
            )

    def test_naive_scheduled_at_becomes_utc(self):
        # A naive datetime far in the future
        future_naive = datetime(2030, 6, 15, 12, 0, 0)
        m = CreateReminderRequest(
            agent="static",
            payload=StaticReminderPayload(title="T", body="B"),
            scheduled_at=future_naive,
        )
        assert m.scheduled_at.tzinfo is not None  # type: ignore[union-attr]

    def test_valid_cron_repeat(self):
        m = CreateReminderRequest(
            agent="static",
            payload=StaticReminderPayload(title="T", body="B"),
            repeat="0 9 * * *",
        )
        assert m.repeat == "0 9 * * *"

    def test_invalid_cron_repeat(self):
        with pytest.raises(ValidationError, match="Invalid cron expression"):
            CreateReminderRequest(
                agent="static",
                payload=StaticReminderPayload(title="T", body="B"),
                repeat="bad-cron",
            )

    def test_max_occurrences_valid(self):
        m = CreateReminderRequest(
            agent="static",
            payload=StaticReminderPayload(title="T", body="B"),
            max_occurrences=5,
        )
        assert m.max_occurrences == 5

    @pytest.mark.parametrize("val", [0, -1, -100])
    def test_max_occurrences_invalid(self, val):
        with pytest.raises(ValidationError, match="max_occurrences must be greater"):
            CreateReminderRequest(
                agent="static",
                payload=StaticReminderPayload(title="T", body="B"),
                max_occurrences=val,
            )

    def test_stop_after_in_past_raises(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with pytest.raises(ValidationError, match="stop_after must be in the future"):
            CreateReminderRequest(
                agent="static",
                payload=StaticReminderPayload(title="T", body="B"),
                stop_after=past,
            )

    def test_stop_after_valid(self):
        future = self._future_dt(hours=24)
        m = CreateReminderRequest(
            agent="static",
            payload=StaticReminderPayload(title="T", body="B"),
            stop_after=future,
        )
        assert m.stop_after is not None

    def test_serializer_datetime_to_iso(self):
        future = self._future_dt()
        m = CreateReminderRequest(
            agent="static",
            payload=StaticReminderPayload(title="T", body="B"),
            scheduled_at=future,
            base_time=future,
        )
        data = m.model_dump()
        assert isinstance(data["scheduled_at"], str)
        assert isinstance(data["base_time"], str)

    def test_serializer_none_stays_none(self):
        m = CreateReminderRequest(
            agent="static",
            payload=StaticReminderPayload(title="T", body="B"),
        )
        data = m.model_dump()
        assert data["scheduled_at"] is None
        assert data["base_time"] is None


# ---------------------------------------------------------------------------
# CreateReminderToolRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCreateReminderToolRequest:
    def _base_data(self, **overrides) -> dict:
        data: Dict[str, Any] = {
            "payload": {"title": "Reminder", "body": "Don't forget"},
            "user_time": "2025-06-01T10:00:00+05:30",
        }
        data.update(overrides)
        return data

    def test_valid_minimal(self):
        m = CreateReminderToolRequest(**self._base_data())
        assert m.agent == AgentType.STATIC  # default
        assert m.repeat is None
        assert m.scheduled_at is None

    def test_valid_with_scheduled_at(self):
        m = CreateReminderToolRequest(
            **self._base_data(scheduled_at="2030-06-15 09:00:00")
        )
        assert m.scheduled_at == "2030-06-15 09:00:00"

    def test_invalid_cron_repeat(self):
        with pytest.raises(ValidationError, match="Invalid cron expression"):
            CreateReminderToolRequest(**self._base_data(repeat="bad-cron"))

    def test_valid_cron_repeat(self):
        m = CreateReminderToolRequest(**self._base_data(repeat="*/5 * * * *"))
        assert m.repeat == "*/5 * * * *"

    @pytest.mark.parametrize("val", [0, -1])
    def test_max_occurrences_invalid(self, val):
        with pytest.raises(ValidationError, match="max_occurrences must be greater"):
            CreateReminderToolRequest(**self._base_data(max_occurrences=val))

    @pytest.mark.parametrize("offset", ["+05:30", "-08:00", "+00:00"])
    def test_valid_timezone_offsets(self, offset):
        m = CreateReminderToolRequest(**self._base_data(timezone_offset=offset))
        assert m.timezone_offset == offset

    @pytest.mark.parametrize("offset", ["5:30", "UTC", "+5", "05:30", "abc"])
    def test_invalid_timezone_offsets(self, offset):
        with pytest.raises(ValidationError, match="Timezone offset must be"):
            CreateReminderToolRequest(**self._base_data(timezone_offset=offset))

    @pytest.mark.parametrize("offset", ["+05:30", "-08:00", "+00:00"])
    def test_valid_stop_after_timezone_offsets(self, offset):
        m = CreateReminderToolRequest(
            **self._base_data(stop_after_timezone_offset=offset)
        )
        assert m.stop_after_timezone_offset == offset

    @pytest.mark.parametrize("offset", ["5:30", "UTC"])
    def test_invalid_stop_after_timezone_offsets(self, offset):
        with pytest.raises(ValidationError, match="Timezone offset must be"):
            CreateReminderToolRequest(
                **self._base_data(stop_after_timezone_offset=offset)
            )


# ---------------------------------------------------------------------------
# CreateReminderToolRequest.to_create_reminder_request
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCreateReminderToolRequestConversion:
    def _base_data(self, **overrides) -> dict:
        data: Dict[str, Any] = {
            "payload": {"title": "Reminder", "body": "Don't forget"},
            "user_time": "2025-06-01T10:00:00+05:30",
        }
        data.update(overrides)
        return data

    def test_basic_conversion_no_schedule(self):
        m = CreateReminderToolRequest(**self._base_data())
        result = m.to_create_reminder_request()
        assert isinstance(result, CreateReminderRequest)
        assert result.scheduled_at is None
        assert result.stop_after is None

    def test_conversion_with_scheduled_at_user_tz(self):
        m = CreateReminderToolRequest(
            **self._base_data(scheduled_at="2030-06-15 09:00:00")
        )
        result = m.to_create_reminder_request()
        assert result.scheduled_at is not None
        assert result.scheduled_at.tzinfo is not None  # type: ignore[union-attr]

    def test_conversion_with_explicit_tz_offset(self):
        m = CreateReminderToolRequest(
            **self._base_data(
                scheduled_at="2030-06-15 09:00:00",
                timezone_offset="-08:00",
            )
        )
        result = m.to_create_reminder_request()
        assert result.scheduled_at is not None
        offset = result.scheduled_at.utcoffset()  # type: ignore[union-attr]
        assert offset == timedelta(hours=-8)

    def test_conversion_with_stop_after_user_tz(self):
        m = CreateReminderToolRequest(
            **self._base_data(stop_after="2030-12-31 23:59:59")
        )
        result = m.to_create_reminder_request()
        assert result.stop_after is not None
        assert result.stop_after.tzinfo is not None  # type: ignore[union-attr]

    def test_conversion_with_stop_after_explicit_tz(self):
        m = CreateReminderToolRequest(
            **self._base_data(
                stop_after="2030-12-31 23:59:59",
                stop_after_timezone_offset="+03:00",
            )
        )
        result = m.to_create_reminder_request()
        offset = result.stop_after.utcoffset()  # type: ignore[union-attr]
        assert offset == timedelta(hours=3)

    def test_conversion_preserves_all_fields(self):
        m = CreateReminderToolRequest(
            **self._base_data(
                repeat="0 9 * * *",
                max_occurrences=10,
            )
        )
        result = m.to_create_reminder_request()
        assert result.repeat == "0 9 * * *"
        assert result.max_occurrences == 10
        assert result.agent == AgentType.STATIC
        assert result.base_time is not None

    def test_conversion_invalid_scheduled_at_format(self):
        m = CreateReminderToolRequest(**self._base_data(scheduled_at="not-a-datetime"))
        with pytest.raises(ValueError, match="Invalid scheduled_at format"):
            m.to_create_reminder_request()

    def test_conversion_invalid_stop_after_format(self):
        m = CreateReminderToolRequest(**self._base_data(stop_after="not-a-datetime"))
        with pytest.raises(ValueError, match="Invalid stop_after format"):
            m.to_create_reminder_request()

    def test_conversion_user_time_utc_fallback(self):
        """When user_time has no timezone, UTC is used."""
        m = CreateReminderToolRequest(
            payload=StaticReminderPayload(title="T", body="B"),
            user_time="2025-06-01T10:00:00",
            scheduled_at="2030-06-15 09:00:00",
        )
        result = m.to_create_reminder_request()
        assert result.scheduled_at is not None
        assert result.scheduled_at.tzinfo == timezone.utc  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# UpdateReminderRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestUpdateReminderRequest:
    def test_valid_empty(self):
        m = UpdateReminderRequest()
        assert m.agent is None
        assert m.repeat is None
        assert m.status is None

    def test_valid_with_fields(self):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        m = UpdateReminderRequest(
            agent="static",
            repeat="0 9 * * 1",
            scheduled_at=future,
            status=ReminderStatus.PAUSED,
            max_occurrences=5,
            stop_after=future,
            payload=StaticReminderPayload(title="T", body="B"),
        )
        assert m.agent == AgentType.STATIC
        assert m.status == ReminderStatus.PAUSED

    def test_invalid_cron_repeat(self):
        with pytest.raises(ValidationError, match="Invalid cron expression"):
            UpdateReminderRequest(repeat="bad-cron")

    @pytest.mark.parametrize("val", [0, -1])
    def test_max_occurrences_invalid(self, val):
        with pytest.raises(ValidationError, match="max_occurrences must be greater"):
            UpdateReminderRequest(max_occurrences=val)

    def test_stop_after_in_past_raises(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with pytest.raises(ValidationError, match="stop_after must be in the future"):
            UpdateReminderRequest(stop_after=past)

    def test_naive_scheduled_at_becomes_utc(self):
        future_naive = datetime(2030, 6, 15, 12, 0, 0)
        m = UpdateReminderRequest(scheduled_at=future_naive)
        assert m.scheduled_at.tzinfo is not None  # type: ignore[union-attr]

    def test_naive_stop_after_becomes_utc(self):
        future_naive = datetime(2030, 6, 15, 12, 0, 0)
        m = UpdateReminderRequest(stop_after=future_naive)
        assert m.stop_after.tzinfo is not None  # type: ignore[union-attr]

    def test_serializer_datetime_to_iso(self):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        m = UpdateReminderRequest(scheduled_at=future, stop_after=future)
        data = m.model_dump()
        assert isinstance(data["scheduled_at"], str)
        assert isinstance(data["stop_after"], str)

    def test_serializer_none_stays_none(self):
        m = UpdateReminderRequest()
        data = m.model_dump()
        assert data["scheduled_at"] is None
        assert data["stop_after"] is None


# ---------------------------------------------------------------------------
# ReminderResponse
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestReminderResponse:
    def _base_data(self, **overrides) -> dict:
        now = datetime.now(timezone.utc)
        data: Dict[str, Any] = {
            "id": "rem1",
            "user_id": "user1",
            "agent": "static",
            "scheduled_at": now + timedelta(hours=1),
            "status": "scheduled",
            "occurrence_count": 0,
            "payload": {"title": "T", "body": "B"},
            "created_at": now,
            "updated_at": now,
        }
        data.update(overrides)
        return data

    def test_valid_minimal(self):
        m = ReminderResponse(**self._base_data())
        assert m.id == "rem1"
        assert m.agent == AgentType.STATIC
        assert m.status == ReminderStatus.SCHEDULED
        assert m.occurrence_count == 0
        assert m.repeat is None
        assert m.max_occurrences is None
        assert m.stop_after is None

    def test_valid_full(self):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        m = ReminderResponse(
            **self._base_data(
                repeat="0 9 * * *",
                max_occurrences=10,
                stop_after=future,
                occurrence_count=3,
            )
        )
        assert m.repeat == "0 9 * * *"
        assert m.max_occurrences == 10
        assert m.occurrence_count == 3

    def test_payload_as_static(self):
        m = ReminderResponse(**self._base_data())
        assert m.payload.title == "T"  # type: ignore[union-attr]

    def test_payload_as_dict(self):
        m = ReminderResponse(**self._base_data(payload={"custom": "value"}))
        assert isinstance(m.payload, dict)

    def test_serializer_outputs_iso_strings(self):
        m = ReminderResponse(**self._base_data())
        data = m.model_dump()
        assert isinstance(data["scheduled_at"], str)
        assert isinstance(data["created_at"], str)
        assert isinstance(data["updated_at"], str)

    def test_serializer_none_stop_after(self):
        m = ReminderResponse(**self._base_data())
        data = m.model_dump()
        assert data["stop_after"] is None

    @pytest.mark.parametrize(
        "status",
        ["scheduled", "executing", "completed", "failed", "cancelled", "paused"],
    )
    def test_all_statuses(self, status):
        m = ReminderResponse(**self._base_data(status=status))
        assert m.status.value == status


# ---------------------------------------------------------------------------
# ReminderProcessingAgentResult
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestReminderProcessingAgentResult:
    def test_valid(self):
        m = ReminderProcessingAgentResult(
            title="Weather Update",
            body="It will rain today",
            message="Here is your weather update for the day...",
        )
        assert m.title == "Weather Update"
        assert m.body == "It will rain today"
        assert m.message.startswith("Here is")

    def test_missing_title(self):
        with pytest.raises(ValidationError):
            ReminderProcessingAgentResult(body="Body", message="Message")

    def test_missing_body(self):
        with pytest.raises(ValidationError):
            ReminderProcessingAgentResult(title="Title", message="Message")

    def test_missing_message(self):
        with pytest.raises(ValidationError):
            ReminderProcessingAgentResult(title="Title", body="Body")

    def test_all_missing(self):
        with pytest.raises(ValidationError):
            ReminderProcessingAgentResult()
