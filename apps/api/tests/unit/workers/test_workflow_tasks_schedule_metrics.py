"""A scheduled workflow fire is counted by outcome and by how late it was claimed.

Regression: workflow fires never pass through the base scheduler's execute path, so
gaia_scheduled_task_total and its lateness histogram read zero for every workflow run.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from prometheus_client import REGISTRY
import pytest

from app.models.user_models import UserDocument
from app.workers.tasks.workflow_tasks import execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"


def _fires(outcome: str) -> float:
    labels = {"kind": "workflow", "outcome": outcome}
    return REGISTRY.get_sample_value("gaia_scheduled_task_total", labels) or 0.0


def _claims() -> float:
    labels = {"kind": "workflow"}
    return REGISTRY.get_sample_value("gaia_scheduled_task_lateness_seconds_count", labels) or 0.0


def _late_seconds() -> float:
    labels = {"kind": "workflow"}
    return REGISTRY.get_sample_value("gaia_scheduled_task_lateness_seconds_sum", labels) or 0.0


async def _fire(trigger_type: str, run: AsyncMock) -> None:
    workflow = MagicMock()
    workflow.user_id = "6812f0b3c9a14e2b7d5a91cc"
    workflow.steps = []
    workflow.repeat = None
    workflow.activated = True
    workflow.scheduled_at = datetime.now(UTC) - timedelta(seconds=90)
    user = UserDocument.model_validate({"onboarding": {"completed": True}})
    with (
        patch(f"{MODULE}.workflow_scheduler") as scheduler,
        patch(f"{MODULE}.user_repository.get", new_callable=AsyncMock, return_value=user),
        patch(f"{MODULE}.enforce_cost_budget", new_callable=AsyncMock),
        patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
        patch(f"{MODULE}.execute_workflow_as_chat", run),
        patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
        patch(f"{MODULE}._record_execution_failure", new_callable=AsyncMock),
        patch(f"{MODULE}._record_timed_out_fire", new_callable=AsyncMock),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        patch(f"{MODULE}.capture"),
    ):
        scheduler.get_task = AsyncMock(return_value=workflow)
        scheduler.claim_task_for_execution = AsyncMock(return_value=True)
        scheduler.handle_recurring_task = AsyncMock()
        create.return_value = MagicMock(execution_id="exec-1")
        await execute_workflow_by_id({}, "wf-1", {"trigger_type": trigger_type})


@pytest.mark.unit
class TestScheduledFireMetrics:
    @pytest.mark.regression
    async def test_a_scheduled_fire_that_ran_counts_ok_and_its_lateness(self) -> None:
        ok, claims, late = _fires("ok"), _claims(), _late_seconds()

        await _fire("schedule", AsyncMock(return_value=("conv-1", [])))

        assert _fires("ok") == ok + 1
        assert _claims() == claims + 1
        assert 90 <= _late_seconds() - late < 120

    @pytest.mark.regression
    async def test_a_scheduled_fire_that_raised_counts_failed(self) -> None:
        failed, ok = _fires("failed"), _fires("ok")

        with pytest.raises(RuntimeError):
            await _fire("schedule", AsyncMock(side_effect=RuntimeError("model down")))

        assert _fires("failed") == failed + 1
        assert _fires("ok") == ok

    async def test_a_scheduled_fire_cut_off_at_its_deadline_counts_failed(self) -> None:
        failed = _fires("failed")

        with pytest.raises(asyncio.CancelledError):
            await _fire("schedule", AsyncMock(side_effect=asyncio.CancelledError()))

        assert _fires("failed") == failed + 1

    async def test_a_manual_run_is_not_a_scheduled_fire(self) -> None:
        ok, claims = _fires("ok"), _claims()

        await _fire("manual", AsyncMock(return_value=("conv-1", [])))

        assert (_fires("ok"), _claims()) == (ok, claims)
