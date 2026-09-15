"""The durable retry behind a billing change's workflow pause/resume."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from arq import Retry
import pytest

from app.constants.payments import (
    SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY,
    SubscriptionWorkflowSync,
)
from app.services.workflow.subscription_pause import SubscriptionWorkflowSyncIncomplete
from app.workers.tasks.subscription_workflow_tasks import (
    sync_workflows_for_subscription_state,
)

_MOD = "app.workers.tasks.subscription_workflow_tasks"

USER_ID = "507f1f77bcf86cd799439011"


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

        for job_try in (1, 2, 3):
            with (
                patch.dict(f"{_MOD}.SYNC_ACTIONS", _actions(pause, AsyncMock()), clear=True),
                pytest.raises(Retry) as caught,
            ):
                await sync_workflows_for_subscription_state(
                    {"job_try": job_try}, USER_ID, SubscriptionWorkflowSync.PAUSE.value
                )
            defers.append(caught.value.defer_score)

        base = SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY.total_seconds() * 1000
        assert defers == [base, base * 2, base * 4]
