"""A reminder must not fire for a user who is no longer paying.

The HTTP paywall is a middleware; the scheduler never makes an HTTP request, so
a reminder created while subscribed would keep firing (and keep spending) after
the subscription lapsed. ``execute_reminder_by_agent`` is the single choke point
every fire passes through, so the gate lives there.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.reminder_models import ReminderModel, ReminderStatus, StaticReminderPayload
from app.tasks.reminder_tasks import execute_reminder_by_agent

pytestmark = pytest.mark.unit

MODULE = "app.tasks.reminder_tasks"


def _reminder() -> ReminderModel:
    return ReminderModel(
        id="rem-1",
        user_id="user-1",
        agent="static",
        payload=StaticReminderPayload(title="Water the plants", body="Now"),
    )


@pytest.fixture
def lapsed_user():
    with patch(f"{MODULE}.is_subscription_active", AsyncMock(return_value=False)):
        yield


@pytest.mark.usefixtures("lapsed_user")
async def test_free_user_reminder_does_not_fire() -> None:
    with (
        patch(
            f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock
        ) as notify,
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock) as deliver,
        patch(f"{MODULE}.reminder_repository.set_status", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event") as capture,
    ):
        await execute_reminder_by_agent(_reminder())

    notify.assert_not_awaited()
    deliver.assert_not_awaited()
    capture.assert_not_called()


@pytest.mark.usefixtures("lapsed_user")
async def test_free_user_reminder_is_paused_not_cancelled() -> None:
    """Paused, so the scheduler stops re-arming it but resubscribing restores it."""
    with (
        patch(f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock),
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch(f"{MODULE}.reminder_repository.set_status", new_callable=AsyncMock) as set_status,
    ):
        await execute_reminder_by_agent(_reminder())

    set_status.assert_awaited_once_with("rem-1", ReminderStatus.PAUSED)


@pytest.mark.usefixtures("lapsed_user")
async def test_the_pause_is_recorded_on_the_wide_event_with_both_ids() -> None:
    """A paused reminder is a silent stop: the wide event is the only trace.

    ``log.warning`` writes message AND kwargs into the event's ``warnings[]``
    (see libs/shared/py/wide_events.py), so both ids are a queried surface —
    without them "why did my reminder stop?" is unanswerable from Loki.
    """
    with (
        patch(f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock),
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch(f"{MODULE}.reminder_repository.set_status", new_callable=AsyncMock),
        patch(f"{MODULE}.log") as mock_log,
    ):
        await execute_reminder_by_agent(_reminder())

    mock_log.warning.assert_called_once_with(
        "Reminder skipped — subscription required, pausing",
        reminder_id="rem-1",
        user_id="user-1",
    )


async def test_the_gate_asks_about_the_reminders_own_owner() -> None:
    """A gate that checked the wrong user id would pass for everyone."""
    is_active = AsyncMock(return_value=True)
    with (
        patch(f"{MODULE}.is_subscription_active", is_active),
        patch(f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock),
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event"),
    ):
        await execute_reminder_by_agent(_reminder())

    is_active.assert_awaited_once_with("user-1")
