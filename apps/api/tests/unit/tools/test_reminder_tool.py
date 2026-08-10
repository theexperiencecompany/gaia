"""Unit tests for app.agents.tools.reminder_tool."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from app.constants.log_tags import LogTag
from app.models.reminder_models import AgentType, ReminderStatus, StaticReminderPayload
from app.utils.timezone import Timezone

# ---------------------------------------------------------------------------
# Module-level patch for rate limiting
# ---------------------------------------------------------------------------
_rl_patch = patch(
    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
    new_callable=AsyncMock,
    return_value={},
)
_rl_patch.start()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.reminder_tool"


def _cfg(user_id: str = FAKE_USER_ID, user_timezone: str = "Asia/Kolkata") -> dict[str, Any]:
    return {"configurable": {"user_id": user_id, "user_timezone": user_timezone}}


def _cfg_no_user() -> dict[str, Any]:
    return {"configurable": {}}


def _reminder_mock(**overrides: Any) -> MagicMock:
    defaults = {
        "id": "rem-1",
        "user_id": FAKE_USER_ID,
        "agent": "static",
        "payload": {"title": "Test", "body": "Body"},
        "status": "scheduled",
    }
    defaults.update(overrides)
    mock = MagicMock()
    mock.model_dump.return_value = defaults
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


# ---------------------------------------------------------------------------
# Tests: create_reminder_tool
# ---------------------------------------------------------------------------


class TestCreateReminderTool:
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        """All optional fields flow into the service request; absolute times
        are interpreted in the user's home zone when no offset is given."""
        mock_scheduler.create_reminder = AsyncMock()

        from app.agents.tools.reminder_tool import create_reminder_tool

        payload = StaticReminderPayload(title="Wake up", body="Time to wake up")
        result = await create_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(),
            payload=payload,
            repeat="0 9 * * *",
            scheduled_at="2099-03-21 08:00:00",
            max_occurrences=3,
            stop_after="2099-06-01 10:00:00",
        )
        assert result == "Reminder created successfully"
        mock_log.set.assert_called_once_with(
            tool={"name": "create_reminder_tool", "action": "create"}
        )
        await_args = mock_scheduler.create_reminder.await_args
        assert await_args is not None
        assert await_args.kwargs == {"user_id": FAKE_USER_ID}
        request = await_args.args[0]
        assert request.agent == AgentType.STATIC
        assert request.payload == payload
        assert request.repeat == "0 9 * * *"
        assert request.max_occurrences == 3
        kolkata = Timezone.parse("Asia/Kolkata").tzinfo
        assert request.scheduled_at == datetime(2099, 3, 21, 8, 0, tzinfo=kolkata)
        assert request.stop_after == datetime(2099, 6, 1, 10, 0, tzinfo=kolkata)
        assert request.timezone == "Asia/Kolkata"

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_delay_seconds_computes_absolute_time(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        """A relative delay becomes now+delay in UTC, and the recurrence zone
        falls back to the home zone (no explicit offset given)."""
        mock_scheduler.create_reminder = AsyncMock()

        from app.agents.tools.reminder_tool import create_reminder_tool

        payload = StaticReminderPayload(title="Wake up", body="Time to wake up")
        result = await create_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), payload=payload, delay_seconds=90
        )
        assert result == "Reminder created successfully"
        request = mock_scheduler.create_reminder.await_args.args[0]
        expected = datetime.now(UTC) + timedelta(seconds=90)
        assert abs((request.scheduled_at - expected).total_seconds()) <= 5
        assert request.timezone == "Asia/Kolkata"

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_explicit_timezone_offsets_win(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        """Explicit offsets localize the times and win over the home zone for
        the recurrence timezone."""
        mock_scheduler.create_reminder = AsyncMock()

        from app.agents.tools.reminder_tool import create_reminder_tool

        payload = StaticReminderPayload(title="Wake up", body="Time to wake up")
        result = await create_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(),
            payload=payload,
            scheduled_at="2099-03-21 08:00:00",
            timezone_offset="+05:30",
            stop_after="2099-06-01 10:00:00",
            stop_after_timezone_offset="+02:00",
        )
        assert result == "Reminder created successfully"
        request = mock_scheduler.create_reminder.await_args.args[0]
        assert request.scheduled_at == datetime(
            2099, 3, 21, 8, 0, tzinfo=Timezone.parse("+05:30").tzinfo
        )
        assert request.stop_after == datetime(
            2099, 6, 1, 10, 0, tzinfo=Timezone.parse("+02:00").tzinfo
        )
        assert request.timezone == "+05:30"

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import create_reminder_tool

        payload = StaticReminderPayload(title="Test", body="Body")
        result = await create_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), payload=payload
        )
        assert result == {"error": "User ID is required to create a reminder"}

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_validation_error(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        """An invalid cron raises a validation error that is logged with the
        exception type and returned to the caller."""
        from app.agents.tools.reminder_tool import create_reminder_tool

        payload = StaticReminderPayload(title="Test", body="Body")
        result = await create_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), payload=payload, repeat="bad-cron"
        )
        assert "Invalid cron expression: bad-cron" in result["error"]
        mock_log.error.assert_called_once_with(
            f"{LogTag.TOOL} Validation error", error_type="ValidationError"
        )
        mock_scheduler.create_reminder.assert_not_called()

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.create_reminder = AsyncMock(side_effect=RuntimeError("DB down"))

        from app.agents.tools.reminder_tool import create_reminder_tool

        payload = StaticReminderPayload(title="Test", body="Body")
        result = await create_reminder_tool.coroutine(config=_cfg(), payload=payload)  # type: ignore[attr-defined]
        assert result == {"error": "DB down"}
        mock_log.exception.assert_called_once_with(
            f"{LogTag.TOOL} Exception occurred while creating reminder"
        )


# ---------------------------------------------------------------------------
# Tests: list_user_reminders_tool
# ---------------------------------------------------------------------------


class TestListUserRemindersTool:
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        r1 = _reminder_mock(id="r1")
        r2 = _reminder_mock(id="r2")
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[r1, r2])

        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert result == [r1.model_dump(), r2.model_dump()]
        mock_log.set.assert_called_once_with(
            tool={"name": "list_user_reminders_tool", "action": "list"}
        )
        mock_scheduler.list_user_reminders.assert_awaited_once_with(
            user_id=FAKE_USER_ID, status=None, limit=100, skip=0
        )

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_status_filter_passthrough(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[])

        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), status=ReminderStatus.COMPLETED
        )
        assert result == []
        mock_scheduler.list_user_reminders.assert_awaited_once_with(
            user_id=FAKE_USER_ID, status=ReminderStatus.COMPLETED, limit=100, skip=0
        )

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg_no_user())  # type: ignore[attr-defined]
        assert result == {"error": "User ID is required to list reminders"}

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_empty_list(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[])

        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert result == []

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.list_user_reminders = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert result == {"error": "err"}
        mock_log.exception.assert_called_once_with(
            f"{LogTag.TOOL} Exception occurred while listing reminders"
        )


# ---------------------------------------------------------------------------
# Tests: get_reminder_tool
# ---------------------------------------------------------------------------


class TestGetReminderTool:
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        reminder = _reminder_mock()
        mock_scheduler.get_reminder = AsyncMock(return_value=reminder)

        from app.agents.tools.reminder_tool import get_reminder_tool

        result = await get_reminder_tool.coroutine(config=_cfg(), reminder_id="rem-1")  # type: ignore[attr-defined]
        assert result == reminder.model_dump()
        mock_log.set.assert_called_once_with(tool={"name": "get_reminder_tool", "action": "get"})
        mock_scheduler.get_reminder.assert_awaited_once_with("rem-1", FAKE_USER_ID)

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_not_found(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.get_reminder = AsyncMock(return_value=None)

        from app.agents.tools.reminder_tool import get_reminder_tool

        result = await get_reminder_tool.coroutine(config=_cfg(), reminder_id="bad")  # type: ignore[attr-defined]
        assert result == {"error": "Reminder not found"}

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import get_reminder_tool

        result = await get_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), reminder_id="r1"
        )
        assert result == {"error": "User ID is required to get reminder"}

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.get_reminder = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import get_reminder_tool

        result = await get_reminder_tool.coroutine(config=_cfg(), reminder_id="r1")  # type: ignore[attr-defined]
        assert result == {"error": "err"}
        mock_log.exception.assert_called_once_with(
            f"{LogTag.TOOL} Exception occurred while getting reminder"
        )


# ---------------------------------------------------------------------------
# Tests: delete_reminder_tool
# ---------------------------------------------------------------------------


class TestDeleteReminderTool:
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.cancel_task = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import delete_reminder_tool

        result = await delete_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1"
        )
        assert result == {"status": "cancelled"}
        mock_log.set.assert_called_once_with(
            tool={"name": "delete_reminder_tool", "action": "delete"}
        )
        mock_scheduler.cancel_task.assert_awaited_once_with("rem-1", FAKE_USER_ID)

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_cancel_failed(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.cancel_task = AsyncMock(return_value=False)

        from app.agents.tools.reminder_tool import delete_reminder_tool

        result = await delete_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1"
        )
        assert result == {"error": "Failed to cancel reminder"}

    @patch(f"{MODULE}.log")
    async def test_no_user_id(self, mock_log: MagicMock) -> None:
        from app.agents.tools.reminder_tool import delete_reminder_tool

        result = await delete_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), reminder_id="r1"
        )
        assert result == {"error": "User ID is required to delete reminder"}
        mock_log.error.assert_called_once_with(f"{LogTag.TOOL} Missing user_id in config")

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.cancel_task = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import delete_reminder_tool

        result = await delete_reminder_tool.coroutine(config=_cfg(), reminder_id="r1")  # type: ignore[attr-defined]
        assert result == {"error": "err"}
        mock_log.exception.assert_called_once_with(
            f"{LogTag.TOOL} Exception occurred while deleting reminder"
        )


# ---------------------------------------------------------------------------
# Tests: update_reminder_tool
# ---------------------------------------------------------------------------


class TestUpdateReminderTool:
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path_repeat(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.update_reminder = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1", repeat="0 9 * * *"
        )
        assert result == {"status": "updated"}
        mock_log.set.assert_called_once_with(
            tool={"name": "update_reminder_tool", "action": "update"}
        )
        update = mock_scheduler.update_reminder.await_args.args[1]
        assert update.repeat == "0 9 * * *"
        # Only the field the caller touched is set — the repository's $set uses
        # exclude_unset, so anything else here would null out stored data.
        assert update.model_fields_set == {"repeat"}
        mock_scheduler.update_reminder.assert_awaited_once_with("rem-1", update, FAKE_USER_ID)

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_update_with_stop_after_and_tz(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_scheduler.update_reminder = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(),
            reminder_id="rem-1",
            stop_after="2026-06-01 12:00:00",
            stop_after_timezone_offset="+05:30",
        )
        assert result == {"status": "updated"}
        update = mock_scheduler.update_reminder.await_args.args[1]
        assert update.stop_after == datetime(
            2026, 6, 1, 12, 0, tzinfo=Timezone.parse("+05:30").tzinfo
        )

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_update_with_naive_stop_after(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        """An absolute time with no timezone stays naive — the repository and
        recovery scan keep the raw wall-clock value."""
        mock_scheduler.update_reminder = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1", stop_after="2026-06-01 12:00:00"
        )
        assert result == {"status": "updated"}
        update = mock_scheduler.update_reminder.await_args.args[1]
        assert update.stop_after == datetime(2026, 6, 1, 12, 0)

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_update_failed(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.update_reminder = AsyncMock(return_value=False)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1", max_occurrences=5
        )
        assert result == {"error": "Failed to update reminder"}
        update = mock_scheduler.update_reminder.await_args.args[1]
        assert update.max_occurrences == 5
        mock_log.error.assert_called_once_with(f"{LogTag.TOOL} Failed to update reminder")

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), reminder_id="r1"
        )
        assert result == {"error": "User ID is required to update reminder"}

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_invalid_stop_after_format(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="r1", stop_after="not-a-date"
        )
        assert result == {
            "error": "Invalid stop_after format: not-a-date. Use YYYY-MM-DD HH:MM:SS format."
        }
        mock_log.error.assert_called_once_with(
            f"{LogTag.TOOL} Invalid stop_after format",
            stop_after="not-a-date",
            error_type="ValueError",
        )
        mock_scheduler.update_reminder.assert_not_called()

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.update_reminder = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="r1", repeat="0 9 * * *"
        )
        assert result == {"error": "err"}
        mock_log.exception.assert_called_once_with(
            f"{LogTag.TOOL} Exception occurred while updating reminder"
        )

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_update_with_payload(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_scheduler.update_reminder = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(),
            reminder_id="rem-1",
            payload={"title": "New title", "body": "New body"},
        )
        assert result == {"status": "updated"}
        update = mock_scheduler.update_reminder.await_args.args[1]
        assert update.payload == StaticReminderPayload(title="New title", body="New body")
        assert update.model_fields_set == {"payload"}

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_update_with_incomplete_payload_rejected(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        """A payload missing ``body`` never reaches the scheduler — StaticReminderPayload
        requires both fields, and the reminder document would be unreadable without it."""
        mock_scheduler.update_reminder = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await cast(Any, update_reminder_tool).coroutine(
            config=_cfg(), reminder_id="rem-1", payload={"title": "New title"}
        )
        assert "body" in result["error"]
        mock_scheduler.update_reminder.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: search_reminders_tool
# ---------------------------------------------------------------------------


class TestSearchRemindersTool:
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        r1 = _reminder_mock(id="r1", payload={"title": "Meeting", "body": "Standup"})
        r2 = _reminder_mock(id="r2", payload={"title": "Gym", "body": "Workout"})
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[r1, r2])

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg(), query="Meeting")  # type: ignore[attr-defined]
        # Only r1 should match
        assert result == [r1.model_dump()]
        mock_log.set.assert_called_once_with(
            tool={"name": "search_reminders_tool", "action": "search"}
        )
        mock_scheduler.list_user_reminders.assert_awaited_once_with(
            user_id=FAKE_USER_ID, limit=100, skip=0
        )

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_no_match(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        r1 = _reminder_mock(id="r1", payload={"title": "Gym", "body": "Workout"})
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[r1])

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), query="ZZZ_NONEXISTENT"
        )
        assert result == []

    @patch(f"{MODULE}.log")
    async def test_no_user_id(self, mock_log: MagicMock) -> None:
        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg_no_user(), query="X")  # type: ignore[attr-defined]
        assert result == {"error": "User ID is required to search reminders"}
        mock_log.error.assert_called_once_with(f"{LogTag.TOOL} Missing user_id in config")

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock, mock_log: MagicMock) -> None:
        mock_scheduler.list_user_reminders = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg(), query="X")  # type: ignore[attr-defined]
        assert result == {"error": "err"}
        mock_log.exception.assert_called_once_with(
            f"{LogTag.TOOL} Exception occurred while searching reminders"
        )

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_case_insensitive_search(
        self, mock_scheduler: MagicMock, mock_log: MagicMock
    ) -> None:
        r1 = _reminder_mock(id="r1", payload={"title": "MEETING", "body": "standup"})
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[r1])

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg(), query="meeting")  # type: ignore[attr-defined]
        assert result == [r1.model_dump()]
