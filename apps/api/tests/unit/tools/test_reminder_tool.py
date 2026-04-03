"""Unit tests for app.agents.tools.reminder_tool."""

from datetime import datetime, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def _cfg(
    user_id: str = FAKE_USER_ID, user_time: str = "2026-03-20T10:00:00"
) -> Dict[str, Any]:
    return {"configurable": {"user_id": user_id, "user_time": user_time}}


def _cfg_no_user() -> Dict[str, Any]:
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
# Tests: _apply_timezone_offset
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyTimezoneOffset:
    def test_positive_offset(self) -> None:
        from app.agents.tools.reminder_tool import _apply_timezone_offset

        dt = datetime(2026, 3, 20, 10, 0, 0)
        result = _apply_timezone_offset(dt, "+05:30")
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(hours=5, minutes=30)

    def test_negative_offset(self) -> None:
        from app.agents.tools.reminder_tool import _apply_timezone_offset

        dt = datetime(2026, 3, 20, 10, 0, 0)
        result = _apply_timezone_offset(dt, "-08:00")
        assert result.utcoffset() == timedelta(hours=-8)

    def test_zero_offset(self) -> None:
        from app.agents.tools.reminder_tool import _apply_timezone_offset

        dt = datetime(2026, 3, 20, 10, 0, 0)
        result = _apply_timezone_offset(dt, "+00:00")
        assert result.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# Tests: create_reminder_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateReminderTool:
    @patch(f"{MODULE}.reminder_scheduler")
    @patch(f"{MODULE}.CreateReminderToolRequest")
    async def test_happy_path(
        self, mock_req_cls: MagicMock, mock_scheduler: MagicMock
    ) -> None:
        mock_instance = MagicMock()
        mock_instance.to_create_reminder_request.return_value = MagicMock()
        mock_req_cls.return_value = mock_instance
        mock_scheduler.create_reminder = AsyncMock()

        from app.agents.tools.reminder_tool import create_reminder_tool
        from app.models.reminder_models import StaticReminderPayload

        payload = StaticReminderPayload(title="Wake up", body="Time to wake up")
        result = await create_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(),
            payload=payload,
            scheduled_at="2026-03-21 08:00:00",
        )
        assert result == "Reminder created successfully"
        mock_scheduler.create_reminder.assert_awaited_once()

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import create_reminder_tool
        from app.models.reminder_models import StaticReminderPayload

        payload = StaticReminderPayload(title="Test", body="Body")
        result = await create_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), payload=payload
        )
        assert result == {"error": "User ID is required to create a reminder"}

    async def test_no_user_time(self) -> None:
        from app.agents.tools.reminder_tool import create_reminder_tool
        from app.models.reminder_models import StaticReminderPayload

        payload = StaticReminderPayload(title="Test", body="Body")
        cfg = {"configurable": {"user_id": FAKE_USER_ID, "user_time": ""}}
        result = await create_reminder_tool.coroutine(config=cfg, payload=payload)  # type: ignore[attr-defined]
        assert result == {"error": "User time is required to create a reminder"}

    @patch(f"{MODULE}.reminder_scheduler")
    @patch(
        f"{MODULE}.CreateReminderToolRequest", side_effect=ValueError("Invalid cron")
    )
    async def test_validation_error(
        self, mock_req_cls: MagicMock, mock_scheduler: MagicMock
    ) -> None:
        from app.agents.tools.reminder_tool import create_reminder_tool
        from app.models.reminder_models import StaticReminderPayload

        payload = StaticReminderPayload(title="Test", body="Body")
        result = await create_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), payload=payload, repeat="bad-cron"
        )
        assert "Invalid cron" in result["error"]

    @patch(f"{MODULE}.reminder_scheduler")
    @patch(f"{MODULE}.CreateReminderToolRequest")
    async def test_service_error(
        self, mock_req_cls: MagicMock, mock_scheduler: MagicMock
    ) -> None:
        mock_instance = MagicMock()
        mock_instance.to_create_reminder_request.return_value = MagicMock()
        mock_req_cls.return_value = mock_instance
        mock_scheduler.create_reminder = AsyncMock(side_effect=RuntimeError("DB down"))

        from app.agents.tools.reminder_tool import create_reminder_tool
        from app.models.reminder_models import StaticReminderPayload

        payload = StaticReminderPayload(title="Test", body="Body")
        result = await create_reminder_tool.coroutine(config=_cfg(), payload=payload)  # type: ignore[attr-defined]
        assert "DB down" in result["error"]


# ---------------------------------------------------------------------------
# Tests: list_user_reminders_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListUserRemindersTool:
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock) -> None:
        r1 = _reminder_mock(id="r1")
        r2 = _reminder_mock(id="r2")
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[r1, r2])

        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert isinstance(result, list)
        assert len(result) == 2

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg_no_user())  # type: ignore[attr-defined]
        assert result == {"error": "User ID is required to list reminders"}

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_empty_list(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[])

        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert result == []

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.list_user_reminders = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert "err" in result["error"]


# ---------------------------------------------------------------------------
# Tests: get_reminder_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetReminderTool:
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.get_reminder = AsyncMock(return_value=_reminder_mock())

        from app.agents.tools.reminder_tool import get_reminder_tool

        result = await get_reminder_tool.coroutine(config=_cfg(), reminder_id="rem-1")  # type: ignore[attr-defined]
        assert result["id"] == "rem-1"

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_not_found(self, mock_scheduler: MagicMock) -> None:
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

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.get_reminder = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import get_reminder_tool

        result = await get_reminder_tool.coroutine(config=_cfg(), reminder_id="r1")  # type: ignore[attr-defined]
        assert "err" in result["error"]


# ---------------------------------------------------------------------------
# Tests: delete_reminder_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteReminderTool:
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.cancel_task = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import delete_reminder_tool

        result = await delete_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1"
        )
        assert result == {"status": "cancelled"}

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_cancel_failed(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.cancel_task = AsyncMock(return_value=False)

        from app.agents.tools.reminder_tool import delete_reminder_tool

        result = await delete_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1"
        )
        assert result == {"error": "Failed to cancel reminder"}

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import delete_reminder_tool

        result = await delete_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), reminder_id="r1"
        )
        assert result == {"error": "User ID is required to delete reminder"}

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.cancel_task = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import delete_reminder_tool

        result = await delete_reminder_tool.coroutine(config=_cfg(), reminder_id="r1")  # type: ignore[attr-defined]
        assert "err" in result["error"]


# ---------------------------------------------------------------------------
# Tests: update_reminder_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateReminderTool:
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path_repeat(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.update_reminder = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1", repeat="0 9 * * *"
        )
        assert result == {"status": "updated"}
        call_args = mock_scheduler.update_reminder.call_args
        assert call_args[0][1]["repeat"] == "0 9 * * *"

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_update_with_stop_after_and_tz(
        self, mock_scheduler: MagicMock
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
        update_data = mock_scheduler.update_reminder.call_args[0][1]
        assert update_data["stop_after"].utcoffset() == timedelta(hours=5, minutes=30)

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_update_failed(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.update_reminder = AsyncMock(return_value=False)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1", max_occurrences=5
        )
        assert result == {"error": "Failed to update reminder"}

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), reminder_id="r1"
        )
        assert result == {"error": "User ID is required to update reminder"}

    async def test_invalid_stop_after_format(self) -> None:
        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="r1", stop_after="not-a-date"
        )
        assert "Invalid stop_after format" in result["error"]

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.update_reminder = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="r1", repeat="0 9 * * *"
        )
        assert "err" in result["error"]

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_update_with_payload(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.update_reminder = AsyncMock(return_value=True)

        from app.agents.tools.reminder_tool import update_reminder_tool

        result = await update_reminder_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), reminder_id="rem-1", payload={"title": "New title"}
        )
        assert result == {"status": "updated"}
        update_data = mock_scheduler.update_reminder.call_args[0][1]
        assert update_data["payload"]["title"] == "New title"


# ---------------------------------------------------------------------------
# Tests: search_reminders_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchRemindersTool:
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_happy_path(self, mock_scheduler: MagicMock) -> None:
        r1 = _reminder_mock(id="r1", payload={"title": "Meeting", "body": "Standup"})
        r2 = _reminder_mock(id="r2", payload={"title": "Gym", "body": "Workout"})
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[r1, r2])

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg(), query="Meeting")  # type: ignore[attr-defined]
        # Only r1 should match
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == "r1"

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_no_match(self, mock_scheduler: MagicMock) -> None:
        r1 = _reminder_mock(id="r1", payload={"title": "Gym", "body": "Workout"})
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[r1])

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), query="ZZZ_NONEXISTENT"
        )
        assert result == []

    async def test_no_user_id(self) -> None:
        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg_no_user(), query="X")  # type: ignore[attr-defined]
        assert result == {"error": "User ID is required to search reminders"}

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_service_error(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.list_user_reminders = AsyncMock(side_effect=RuntimeError("err"))

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg(), query="X")  # type: ignore[attr-defined]
        assert "err" in result["error"]

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_case_insensitive_search(self, mock_scheduler: MagicMock) -> None:
        r1 = _reminder_mock(id="r1", payload={"title": "MEETING", "body": "standup"})
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[r1])

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg(), query="meeting")  # type: ignore[attr-defined]
        assert len(result) == 1
