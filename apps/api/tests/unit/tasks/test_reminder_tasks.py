"""Unit tests for the static reminder task handlers (app.tasks.reminder_tasks).

Pins the payload validation, the in-app notification wiring, and — the fix for
reminders being invisible to later turns — the delivery of a fired reminder into
the user's chat platforms via the shared ``deliver_result_to_platforms`` path,
which records it into the conversation's langgraph thread.
"""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.models.reminder_models import ReminderModel, StaticReminderPayload
from app.services.analytics_service import AnalyticsEvents
from app.tasks.reminder_tasks import _execute_static_reminder, execute_reminder_by_agent

MODULE = "app.tasks.reminder_tasks"


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
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch("app.tasks.reminder_tasks.log.info") as log_info,
    ):
        await _execute_static_reminder(reminder)

    create.assert_awaited_once()
    notification = create.await_args.args[0]
    assert notification.user_id == "user-1"
    assert notification.content.title == "Water the plants"
    # The in-app badge must NOT auto-inject the external platforms: the chat-platform
    # copy is delivered (and recorded) by _deliver_reminder_to_platforms instead.
    assert [c.channel_type for c in notification.channels] == [CHANNEL_TYPE_INAPP]
    log_info.assert_called_once()


async def test_reminder_execution_captures_completed() -> None:
    reminder = _reminder()

    with (
        patch(
            "app.tasks.reminder_tasks.notification_service.create_notification",
            new_callable=AsyncMock,
        ),
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
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
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch("app.tasks.reminder_tasks.capture_event") as mock_capture,
        patch("app.tasks.reminder_tasks.log.info"),
    ):
        with pytest.raises(RuntimeError, match="notify down"):
            await execute_reminder_by_agent(reminder)

    mock_capture.assert_not_called()


class TestReminderReachesChatPlatforms:
    """A fired reminder must be delivered into the user's chat platforms through
    the SAME path a finished workflow uses (``deliver_result_to_platforms``), which
    records the delivery into the conversation's langgraph thread. Before this fix
    the reminder was sent only as a notification and left no trace in the thread,
    so a later turn had no memory it fired and could not backtrack to it."""

    @pytest.mark.regression
    async def test_fired_reminder_is_delivered_to_platforms_with_backtrackable_origin(
        self,
    ) -> None:
        reminder = _reminder()

        with (
            patch(
                "app.tasks.reminder_tasks.notification_service.create_notification",
                new_callable=AsyncMock,
            ),
            patch(
                f"{MODULE}.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": "user-1", "email": "u@gaia.local"},
            ),
            patch(f"{MODULE}.deliver_result_to_platforms", new_callable=AsyncMock) as deliver,
            patch("app.tasks.reminder_tasks.log.info"),
        ):
            await _execute_static_reminder(reminder)

        deliver.assert_awaited_once()
        kwargs = deliver.await_args.kwargs
        assert kwargs["user_id"] == "user-1"
        # The origin names the reminder (title + machine id) so the langgraph
        # record it produces can be backtracked to this reminder.
        assert kwargs["origin"] == 'reminder "Water the plants" (id rem-1)'
        # The delivered text carries the reminder content GAIA would voice.
        assert "Water the plants" in kwargs["notification_text"]
        assert "Now" in kwargs["notification_text"]

    async def test_platform_delivery_skipped_when_user_missing(self) -> None:
        reminder = _reminder()

        with (
            patch(
                "app.tasks.reminder_tasks.notification_service.create_notification",
                new_callable=AsyncMock,
            ),
            patch(f"{MODULE}.get_user_by_id", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.deliver_result_to_platforms", new_callable=AsyncMock) as deliver,
            patch("app.tasks.reminder_tasks.log.info"),
        ):
            await _execute_static_reminder(reminder)

        # No user resolved -> get_or_create_session would key the wrong owner, so
        # the platform delivery must be skipped rather than guessed.
        deliver.assert_not_awaited()

    async def test_platform_delivery_failure_never_fails_the_reminder(self) -> None:
        """The platform delivery is a side channel — the in-app badge is the
        primary delivery. A transient user-lookup failure (get_user_by_id raises
        HTTPException) must be swallowed, not propagated: the reminder still
        completes and is captured, and a recurring one is not skipped."""
        reminder = _reminder()

        with (
            patch(
                "app.tasks.reminder_tasks.notification_service.create_notification",
                new_callable=AsyncMock,
            ) as create,
            patch(
                f"{MODULE}.get_user_by_id",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404, detail="User not found"),
            ),
            patch(f"{MODULE}.capture_event") as mock_capture,
            patch("app.tasks.reminder_tasks.log.info"),
        ):
            # Must not raise despite the lookup blowing up.
            await execute_reminder_by_agent(reminder)

        create.assert_awaited_once()
        # The reminder is treated as successfully executed — the side channel's
        # failure did not mark it failed or skip the completion capture.
        mock_capture.assert_called_once()
        assert mock_capture.call_args.args[1] == AnalyticsEvents.REMINDER_COMPLETED
