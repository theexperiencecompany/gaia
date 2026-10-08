"""The durable retry behind a billing change's workflow pause/resume."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from arq import Retry
import pytest

from app.constants.payments import (
    SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY,
    SUBSCRIPTION_WORKFLOW_SYNC_TASK,
    SubscriptionWorkflowSync,
)
from app.models.reminder_models import AgentType, ReminderDocument, StaticReminderPayload
from app.models.scheduler_models import DeactivationReason, ScheduledTaskStatus
from app.services.payments.subscription_events import resume_paywall_pauses_safely
from app.services.workflow.subscription_pause import SubscriptionWorkflowSyncIncomplete
from app.workers.tasks.subscription_workflow_tasks import (
    sync_workflows_for_subscription_state,
)

_MOD = "app.workers.tasks.subscription_workflow_tasks"
_EVENTS = "app.services.payments.subscription_events"
_REMINDERS = "app.services.reminder_service"
_TODOS = "app.services.tracked_todo_service"

USER_ID = "507f1f77bcf86cd799439011"


def _paused_reminder(reminder_id: str) -> ReminderDocument:
    return ReminderDocument(
        id=reminder_id,
        user_id=USER_ID,
        agent=AgentType.STATIC,
        payload=StaticReminderPayload(title="Meds", body="Take them"),
        status=ScheduledTaskStatus.PAUSED,
        pause_reason=DeactivationReason.SUBSCRIPTION_LAPSED,
    )


def _actions(pause: AsyncMock, resume: AsyncMock) -> dict:
    return {
        SubscriptionWorkflowSync.PAUSE: pause,
        SubscriptionWorkflowSync.RESUME: resume,
    }


@pytest.mark.unit
class TestSyncWorkflowsForSubscriptionState:
    async def test_it_pauses_when_the_billing_change_said_lapsed(self) -> None:
        pause, resume = AsyncMock(return_value=2), AsyncMock()

        with patch.dict(f"{_MOD}.SYNC_ACTIONS", _actions(pause, resume), clear=True):
            result = await sync_workflows_for_subscription_state(
                {}, USER_ID, SubscriptionWorkflowSync.PAUSE.value
            )

        pause.assert_awaited_once_with(USER_ID)
        resume.assert_not_awaited()
        assert "moved 2 workflow(s)" in result

    async def test_it_resumes_when_the_billing_change_said_restored(self) -> None:
        pause, resume = AsyncMock(), AsyncMock(return_value=1)

        with patch.dict(f"{_MOD}.SYNC_ACTIONS", _actions(pause, resume), clear=True):
            await sync_workflows_for_subscription_state(
                {}, USER_ID, SubscriptionWorkflowSync.RESUME.value
            )

        resume.assert_awaited_once_with(USER_ID)
        pause.assert_not_awaited()

    async def test_a_workflow_left_behind_asks_arq_for_another_run(self) -> None:
        """Otherwise the job ends "successfully" with the workflow still armed upstream."""
        pause = AsyncMock(side_effect=SubscriptionWorkflowSyncIncomplete(USER_ID, ["wf-1"]))

        with (
            patch.dict(f"{_MOD}.SYNC_ACTIONS", _actions(pause, AsyncMock()), clear=True),
            pytest.raises(Retry) as caught,
        ):
            await sync_workflows_for_subscription_state(
                {"job_try": 1}, USER_ID, SubscriptionWorkflowSync.PAUSE.value
            )

        assert caught.value.defer_score == SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY / timedelta(
            milliseconds=1
        )
        assert isinstance(caught.value.__cause__, SubscriptionWorkflowSyncIncomplete)

    async def test_each_further_try_waits_longer(self) -> None:
        """A flat interval burns the try budget before a down dependency recovers."""
        pause = AsyncMock(side_effect=RuntimeError("composio down"))
        defers = []
        logged = []

        for job_try in (1, 2, 3):
            with (
                patch.dict(f"{_MOD}.SYNC_ACTIONS", _actions(pause, AsyncMock()), clear=True),
                patch(f"{_MOD}.log") as mock_log,
                pytest.raises(Retry) as caught,
            ):
                await sync_workflows_for_subscription_state(
                    {"job_try": job_try}, USER_ID, SubscriptionWorkflowSync.PAUSE.value
                )
            defers.append(caught.value.defer_score)
            logged.append(mock_log.warning.call_args.kwargs["defer_seconds"])

        base = SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY.total_seconds() * 1000
        assert defers == [base, base * 2, base * 4]
        # The logged wait is what an operator reads; it must be the wait ARQ was given.
        assert logged == [d / 1000 for d in defers]

    async def test_a_context_without_a_try_counter_is_the_first_try(self) -> None:
        """ARQ omits job_try on a bare context, and a wrong first try skews every later backoff."""
        pause = AsyncMock(side_effect=RuntimeError("composio down"))

        with (
            patch.dict(f"{_MOD}.SYNC_ACTIONS", _actions(pause, AsyncMock()), clear=True),
            patch(f"{_MOD}.log") as mock_log,
            pytest.raises(Retry) as caught,
        ):
            await sync_workflows_for_subscription_state(
                {}, USER_ID, SubscriptionWorkflowSync.PAUSE.value
            )

        assert caught.value.defer_score == SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY / timedelta(
            milliseconds=1
        )
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID},
            workflow_sync={"direction": SubscriptionWorkflowSync.PAUSE.value, "try": 1},
        )

    async def test_the_retry_warning_carries_the_user_direction_cause_and_wait(self) -> None:
        resume = AsyncMock(side_effect=SubscriptionWorkflowSyncIncomplete(USER_ID, ["wf-1"]))

        with (
            patch.dict(f"{_MOD}.SYNC_ACTIONS", _actions(AsyncMock(), resume), clear=True),
            patch(f"{_MOD}.log") as mock_log,
            pytest.raises(Retry),
        ):
            await sync_workflows_for_subscription_state(
                {"job_try": 3}, USER_ID, SubscriptionWorkflowSync.RESUME.value
            )

        mock_log.warning.assert_called_once()
        assert (
            mock_log.warning.call_args.args[0]
            == "[WORKFLOW] Workflow subscription sync incomplete; retrying"
        )
        assert mock_log.warning.call_args.kwargs == {
            "user_id": USER_ID,
            "direction": SubscriptionWorkflowSync.RESUME.value,
            "error": "1 workflow(s) did not follow the subscription change",
            "error_type": "SubscriptionWorkflowSyncIncomplete",
            "defer_seconds": SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY.total_seconds() * 4,
        }


@pytest.mark.unit
class TestAPaywallResumeThatFailsIsRetriedByTheSameTask:
    @pytest.mark.regression
    async def test_a_reminder_that_could_not_resume_is_resumed_by_the_retry(self) -> None:
        stuck = _paused_reminder("64b64b64b64b64b64b64b64a")
        fine = _paused_reminder("64b64b64b64b64b64b64b64b")
        find = AsyncMock(side_effect=[[stuck, fine], [stuck]])
        update = AsyncMock(side_effect=[ConnectionError("mongo blip"), fine, stuck])
        pool = object()
        with (
            patch(f"{_REMINDERS}.reminder_repository.find_paused_for_reason", find),
            patch(f"{_REMINDERS}.reminder_repository.update_for_user", update),
            patch(f"{_TODOS}.todo_repository.find_paused_for_reason", AsyncMock(return_value=[])),
            patch(f"{_EVENTS}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
            patch(f"{_EVENTS}.enqueue_worker_job", new_callable=AsyncMock) as enqueue,
        ):
            await resume_paywall_pauses_safely(USER_ID)
            enqueue.assert_awaited_once_with(
                pool,
                SUBSCRIPTION_WORKFLOW_SYNC_TASK,
                USER_ID,
                SubscriptionWorkflowSync.RESUME_PAUSED.value,
                _job_id=f"{SUBSCRIPTION_WORKFLOW_SYNC_TASK}:{USER_ID}:resume_paused",
            )

            await sync_workflows_for_subscription_state(
                {"job_try": 1}, USER_ID, enqueue.await_args.args[3]
            )

        assert [c.args[0] for c in update.await_args_list] == [stuck.id, fine.id, stuck.id]
        assert all(
            c.args[2].status is ScheduledTaskStatus.SCHEDULED for c in update.await_args_list
        )
