"""A reminder must not fire for a user who is no longer paying.

The HTTP paywall is a middleware; the scheduler never makes an HTTP request, so
a reminder created while subscribed would keep firing (and keep spending) after
the subscription lapsed. ``execute_reminder_by_agent`` is the single choke point
every fire passes through, so the gate lives there.

The gate only SKIPS. It used to write ``PAUSED`` as well, which was invisible:
``BaseSchedulerService.process_task_execution`` writes the reminder's status
again the moment the fire returns — ``SCHEDULED`` for a recurring reminder,
``COMPLETED`` for a one-off — so the pause was overwritten every time and no
subscription-restore path had anything to resume from. Skipping instead lets
the scheduler's own re-arm bring a recurring reminder back by itself, which is
what the workflow gate does for the same reason.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.decorators import entitlements
from app.models.payment_models import PlanType
from app.models.reminder_models import ReminderModel, ReminderStatus, StaticReminderPayload
from app.services.analytics_service import AnalyticsEvents
from app.services.reminder_service import reminder_scheduler
from app.tasks.reminder_tasks import PAYWALL_FEATURE_REMINDER, execute_reminder_by_agent

pytestmark = pytest.mark.unit

MODULE = "app.tasks.reminder_tasks"
SCHEDULER = "app.services.reminder_service"


def _reminder(repeat: str | None = None) -> ReminderModel:
    return ReminderModel(
        id="rem-1",
        user_id="user-1",
        agent="static",
        repeat=repeat,
        scheduled_at=datetime.now(UTC),
        payload=StaticReminderPayload(title="Water the plants", body="Now"),
    )


@pytest.fixture
def lapsed_user():
    """FREE in the cache AND on a fresh read — a genuinely lapsed subscription."""
    with (
        patch(f"{MODULE}.is_paid", AsyncMock(return_value=False)),
    ):
        yield


@pytest.mark.usefixtures("lapsed_user")
async def test_free_user_reminder_does_not_fire() -> None:
    with (
        patch(
            f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock
        ) as notify,
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock) as deliver,
        patch(f"{MODULE}.capture_event") as capture,
    ):
        await execute_reminder_by_agent(_reminder())

    notify.assert_not_awaited()
    deliver.assert_not_awaited()
    captured = [call.args[1] for call in capture.call_args_list]
    assert AnalyticsEvents.REMINDER_COMPLETED not in captured


@pytest.mark.usefixtures("lapsed_user")
async def test_the_block_reaches_the_funnel_under_the_blocked_users_own_id() -> None:
    """Every other paywall block in the app is attributable; this one must be too.

    This gate cannot go through ``require_active_subscription`` — that raises,
    and a worker must skip — so the event it would have fired has to be fired
    here. Without it "how many users lost a reminder to the wall" is
    unanswerable while every other surface answers it, and a worker has no
    request context, so the id must be explicit or the block lands on an
    anonymous profile.
    """
    with (
        patch(f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock),
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event") as capture,
    ):
        await execute_reminder_by_agent(_reminder())

    capture.assert_called_once_with(
        "user-1",
        AnalyticsEvents.PAYWALL_BLOCKED,
        {"feature": PAYWALL_FEATURE_REMINDER},
    )


async def test_a_paying_users_reminder_is_never_captured_as_blocked() -> None:
    with (
        patch(f"{MODULE}.is_paid", AsyncMock(return_value=True)),
        patch(f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock),
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event") as capture,
    ):
        await execute_reminder_by_agent(_reminder())

    captured = [call.args[1] for call in capture.call_args_list]
    assert AnalyticsEvents.PAYWALL_BLOCKED not in captured


@pytest.mark.usefixtures("lapsed_user")
async def test_the_skip_is_recorded_on_the_wide_event_with_both_ids() -> None:
    """A skipped reminder is silent: the wide event is the only trace.

    ``log.warning`` writes message AND kwargs into the event's ``warnings[]``
    (see libs/shared/py/wide_events.py), so both ids are a queried surface —
    without them "why did my reminder stop?" is unanswerable from Loki.
    """
    with (
        patch(f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock),
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch(f"{MODULE}.log") as mock_log,
    ):
        await execute_reminder_by_agent(_reminder())

    mock_log.warning.assert_called_once_with(
        "Reminder skipped — subscription required",
        reminder_id="rem-1",
        user_id="user-1",
    )


async def test_a_user_who_just_paid_fires_off_the_row_not_the_stale_cache() -> None:
    """The cached tier lags a payment by up to its TTL.

    A user who paid two minutes ago still reads FREE from Redis. Refusing an
    HTTP request on that is recoverable — the next one is fine — but a reminder
    occurrence refused on it is gone. The real gate, not a stub of it: cache
    FREE, row PRO, and the reminder fires.
    """
    with (
        patch(f"{MODULE}.is_paid", entitlements.is_paid),
        patch(
            "app.decorators.entitlements.payment_service.get_cached_plan_type",
            AsyncMock(return_value=PlanType.FREE),
        ),
        patch(
            "app.decorators.entitlements.payment_service.get_user_subscription_status",
            AsyncMock(return_value=MagicMock(plan_type=PlanType.PRO)),
        ),
        patch("app.decorators.entitlements.invalidate_plan_cache", new_callable=AsyncMock),
        patch(
            f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock
        ) as notify,
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event"),
    ):
        await execute_reminder_by_agent(_reminder())

    notify.assert_awaited_once()


async def test_the_gate_asks_about_the_reminders_own_owner() -> None:
    """A gate that checked the wrong user id would pass for everyone."""
    is_active = AsyncMock(return_value=True)
    with (
        patch(f"{MODULE}.is_paid", is_active),
        patch(f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock),
        patch(f"{MODULE}._deliver_reminder_to_platforms", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event"),
    ):
        await execute_reminder_by_agent(_reminder())

    is_active.assert_awaited_once_with("user-1")


@pytest.mark.usefixtures("lapsed_user")
async def test_a_recurring_reminder_the_gate_skipped_is_left_armed_for_its_next_occurrence() -> (
    None
):
    """Driven through the scheduler, because the scheduler is what overwrote the pause.

    ``process_task_execution`` is the path the ARQ job takes: claim, execute,
    then write the status again. Testing the gate alone cannot see that second
    write, which is why the pause it used to take looked correct in isolation
    and was gone in production. Only the reminder repository and the ARQ pool
    are faked; the status the reminder ends up in is whatever the real
    scheduler settles on.
    """
    set_status = AsyncMock(return_value=True)
    with (
        patch(
            f"{SCHEDULER}.reminder_repository.get", AsyncMock(return_value=_reminder("0 9 * * *"))
        ),
        patch(f"{SCHEDULER}.reminder_repository.claim_for_execution", AsyncMock(return_value=True)),
        patch(f"{SCHEDULER}.reminder_repository.set_status", set_status),
    ):
        await reminder_scheduler.process_task_execution("rem-1")

    written = [call.args[1] for call in set_status.await_args_list]
    assert ReminderStatus.PAUSED not in written, (
        f"the gate wrote PAUSED, which the scheduler then overwrote: {written}"
    )
    assert written[-1] is ReminderStatus.SCHEDULED, (
        "a skipped recurring reminder must stay armed so it resumes on its own "
        f"once the user pays again, got {written}"
    )
