"""A fired reminder as the user experiences it: badge, platform ping, one delivery.

Unit tests prove each hop with the neighbours mocked (scheduler with
execute_reminder_by_agent patched out, execute_reminder_by_agent with the
notification service patched out), and test_platform_delivery_recording_e2e
only checks the recording text landed in a thread. Nothing proved the whole
chain with the real scheduler in the middle: ARQ task -> claim -> execute ->
in-app notification + platform delivery -> COMPLETED, exactly once even when
two workers race, and skipped-but-rearmed when the subscription lapses.

Real: ReminderScheduler.process_task_execution (claim/execute/status),
ReminderScheduler.execute_task, execute_reminder_by_agent's static branch.
Doubled: the repository (in-memory, with real claim semantics), the delivery
edges (notification service, conversation + platform delivery), plan reads.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.models.chat_models import ConversationSource
from app.models.reminder_models import AgentType, ReminderModel, StaticReminderPayload
from app.models.scheduler_models import ScheduledTaskStatus
from app.services.reminder_service import ReminderScheduler

pytestmark = pytest.mark.e2e

USER_ID = "507f1f77bcf86cd799439011"
REMINDER_TASKS = "app.tasks.reminder_tasks"


def _make_scheduler() -> ReminderScheduler:
    with patch("app.services.reminder_service.BaseSchedulerService.__init__"):
        scheduler = ReminderScheduler.__new__(ReminderScheduler)
        scheduler.redis_settings = None
        scheduler.arq_pool = None
        return scheduler


def _make_reminder(**overrides) -> ReminderModel:
    data = {
        "_id": str(ObjectId()),
        "user_id": USER_ID,
        "agent": AgentType.STATIC,
        "payload": StaticReminderPayload(title="Standup", body="Join now").model_dump(),
        "repeat": None,
        "scheduled_at": datetime.now(UTC) + timedelta(hours=1),
        "status": ScheduledTaskStatus.SCHEDULED,
        "occurrence_count": 0,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "source_conversation_id": "conv-1",
    }
    data.update(overrides)
    return ReminderModel(**data)


class _MemoryReminderStore:
    """The reminders collection, in process.

    Carries the claim semantics the repository contract suite certifies: a
    claim flips SCHEDULED->EXECUTING atomically, so a second claimant loses."""

    def __init__(self, reminder: ReminderModel) -> None:
        self.reminder = reminder
        self.claims = 0
        self.statuses: list[str] = []

    async def get(self, task_id: str) -> ReminderModel | None:
        return self.reminder if task_id == self.reminder.id else None

    async def claim_for_execution(self, task_id: str, **kwargs) -> bool:
        self.claims += 1
        return self.claims == 1

    async def set_status(self, task_id: str, status, **kwargs) -> bool:
        self.statuses.append(status)
        return True


def _patch_repo(store: _MemoryReminderStore):
    get_m = AsyncMock(side_effect=store.get)
    claim_m = AsyncMock(side_effect=store.claim_for_execution)
    status_m = AsyncMock(side_effect=store.set_status)
    patchers = (
        patch("app.services.reminder_service.reminder_repository.get", new=get_m),
        patch(
            "app.services.reminder_service.reminder_repository.claim_for_execution",
            new=claim_m,
        ),
        patch("app.services.reminder_service.reminder_repository.set_status", new=status_m),
    )
    return patchers, (get_m, claim_m, status_m)


def _patch_delivery_edges(paid: bool = True):
    paid_m = AsyncMock(return_value=paid)
    user_m = AsyncMock(return_value=SimpleNamespace(user_id=USER_ID))
    conv_m = AsyncMock(return_value=ConversationSource.TELEGRAM)
    plat_m = AsyncMock()
    patchers = (
        patch(f"{REMINDER_TASKS}.is_paid", new=paid_m),
        patch(f"{REMINDER_TASKS}.load_user_context", new=user_m),
        patch(f"{REMINDER_TASKS}.deliver_message_to_conversation", new=conv_m),
        patch(f"{REMINDER_TASKS}.deliver_result_to_platforms", new=plat_m),
    )
    return patchers, (paid_m, user_m, conv_m, plat_m)


class TestStaticReminderFiresEndToEnd:
    async def test_fire_raises_badge_and_delivers_to_platforms(self) -> None:
        reminder = _make_reminder()
        store = _MemoryReminderStore(reminder)
        repo_patchers, _ = _patch_repo(store)
        edge_patchers, (_, _, conv_m, plat_m) = _patch_delivery_edges(paid=True)
        with ExitStack() as stack:
            for patcher in (*repo_patchers, *edge_patchers):
                stack.enter_context(patcher)
            create_notification = stack.enter_context(
                patch(
                    "app.services.notification_service.notification_service.create_notification",
                    new_callable=AsyncMock,
                )
            )
            stack.enter_context(patch(f"{REMINDER_TASKS}.capture"))
            result = await _make_scheduler().process_task_execution(reminder.id)

        assert result.success is True
        # The in-app badge is the pinned delivery; the platform send is the side channel.
        create_notification.assert_awaited_once()
        conv_m.assert_awaited_once()
        plat_m.assert_awaited_once()
        assert store.statuses == [ScheduledTaskStatus.COMPLETED]

    async def test_second_worker_loses_the_claim_and_sends_nothing(self) -> None:
        """Two ARQ jobs per reminder is ordinary; the loser must not execute."""
        reminder = _make_reminder()
        store = _MemoryReminderStore(reminder)
        repo_patchers, _ = _patch_repo(store)
        edge_patchers, _ = _patch_delivery_edges(paid=True)
        with ExitStack() as stack:
            for patcher in (*repo_patchers, *edge_patchers):
                stack.enter_context(patcher)
            create_notification = stack.enter_context(
                patch(
                    "app.services.notification_service.notification_service.create_notification",
                    new_callable=AsyncMock,
                )
            )
            stack.enter_context(patch(f"{REMINDER_TASKS}.capture"))
            scheduler = _make_scheduler()
            first = await scheduler.process_task_execution(reminder.id)
            second = await scheduler.process_task_execution(reminder.id)

        assert first.success is True
        assert second.success is False
        assert "not in scheduled status" in (second.message or "")
        create_notification.assert_awaited_once()
        assert store.statuses == [ScheduledTaskStatus.COMPLETED]


class TestLapsedSubscriptionSkipsButRearms:
    async def test_unpaid_recurring_fire_skips_delivery_and_rearms(self) -> None:
        """The gate skips without writing PAUSED, so recurring reminders re-arm on resume."""
        reminder = _make_reminder(repeat="0 9 * * *")
        store = _MemoryReminderStore(reminder)
        repo_patchers, _ = _patch_repo(store)
        edge_patchers, (_, _, conv_m, plat_m) = _patch_delivery_edges(paid=False)
        with ExitStack() as stack:
            for patcher in (*repo_patchers, *edge_patchers):
                stack.enter_context(patcher)
            create_notification = stack.enter_context(
                patch(
                    "app.services.notification_service.notification_service.create_notification",
                    new_callable=AsyncMock,
                )
            )
            capture = stack.enter_context(patch(f"{REMINDER_TASKS}.capture"))
            result = await _make_scheduler().process_task_execution(reminder.id)

        assert result.success is True
        create_notification.assert_not_awaited()
        conv_m.assert_not_awaited()
        plat_m.assert_not_awaited()
        # Re-armed for the next occurrence, not completed away.
        assert store.statuses == [ScheduledTaskStatus.SCHEDULED]
        assert capture.call_count >= 1
