"""Unit tests for the static reminder task handlers (app.tasks.reminder_tasks).

Pins the payload validation and the notification wiring: a static reminder
must produce exactly one AIProactiveNotificationSource notification through
notification_service, and reject invalid payloads loudly.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.reminder_models import ReminderModel, StaticReminderPayload
from app.services.analytics_service import AnalyticsEvents
from app.tasks.reminder_tasks import _execute_static_reminder, execute_reminder_by_agent


def _reminder(**overrides) -> ReminderModel:
    payload = overrides.pop("payload", StaticReminderPayload(title="Water the plants", body="Now"))
    return ReminderModel(
        id="rem-1",
        user_id="user-1",
        agent="static",
        payload=payload,
        **overrides,
    )


async def test_invalid_payload_type_raises() -> None:
    reminder = _reminder(payload={"not": "a static payload"})

    with pytest.raises(ValueError, match="Invalid payload type"):
        await _execute_static_reminder(reminder)


async def test_reminder_without_id_raises() -> None:
    reminder = _reminder()
    reminder.id = None

    with pytest.raises(ValueError, match="must have an ID"):
        await _execute_static_reminder(reminder)


async def test_static_reminder_sends_notification() -> None:
    reminder = _reminder()

    with (
        patch(
            "app.tasks.reminder_tasks.notification_service.create_notification",
            new_callable=AsyncMock,
        ) as create,
        patch("app.tasks.reminder_tasks.log.info") as log_info,
    ):
        await _execute_static_reminder(reminder)

    create.assert_awaited_once()
    notification = create.await_args.args[0]
    assert notification.user_id == "user-1"
    assert notification.content.title == "Water the plants"
    log_info.assert_called_once()


async def test_reminder_execution_captures_completed() -> None:
    reminder = _reminder()

    with (
        patch(
            "app.tasks.reminder_tasks.notification_service.create_notification",
            new_callable=AsyncMock,
        ),
        patch("app.tasks.reminder_tasks.capture_event") as mock_capture,
        patch("app.tasks.reminder_tasks.log.info"),
    ):
        await execute_reminder_by_agent(reminder)

    mock_capture.assert_called_once()
    assert mock_capture.call_args.args[0] == "user-1"
    assert mock_capture.call_args.args[1] == AnalyticsEvents.REMINDER_COMPLETED
    assert mock_capture.call_args.args[2] == {"reminder_id": "rem-1", "agent": "static"}


async def test_reminder_failure_does_not_capture() -> None:
    reminder = _reminder()

    with (
        patch(
            "app.tasks.reminder_tasks.notification_service.create_notification",
            new_callable=AsyncMock,
            side_effect=RuntimeError("notify down"),
        ),
        patch("app.tasks.reminder_tasks.capture_event") as mock_capture,
        patch("app.tasks.reminder_tasks.log.info"),
    ):
        with pytest.raises(RuntimeError, match="notify down"):
            await execute_reminder_by_agent(reminder)

    mock_capture.assert_not_called()
