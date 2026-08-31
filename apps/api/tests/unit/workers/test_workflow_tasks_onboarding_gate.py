"""Unit tests for the onboarding gate in execute_workflow_by_id.

System-initiated runs (schedule/trigger fires) must not execute for a user who
never submitted the onboarding wizard — their auto-created workflows would
drain the daily budget and aim limit messaging at someone who never used the
app. Manual "run now" fires and onboarded users are unaffected.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.tasks.workflow_tasks import execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"


def _workflow(user_id: str = "user-1") -> MagicMock:
    wf = MagicMock()
    wf.user_id = user_id
    wf.steps = []
    wf.repeat = None
    wf.activated = True
    return wf


def _user(completed: bool) -> MagicMock:
    user = MagicMock()
    user.onboarding = {"completed": completed}
    return user


async def _run_task(
    workflow: MagicMock, user: MagicMock, context: dict[str, Any] | None
) -> tuple[str, AsyncMock, AsyncMock]:
    with (
        patch(f"{MODULE}.workflow_scheduler") as scheduler,
        patch(f"{MODULE}.user_repository.get", new_callable=AsyncMock, return_value=user),
        patch(f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock) as budget,
        patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
        patch(
            f"{MODULE}.execute_workflow_as_chat",
            new_callable=AsyncMock,
            return_value=("conv-1", []),
        ),
        patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event"),
    ):
        scheduler.get_task = AsyncMock(return_value=workflow)
        scheduler.claim_task_for_execution = AsyncMock(return_value=True)
        scheduler.handle_recurring_task = AsyncMock()
        create.return_value = MagicMock(execution_id="exec-1")
        result = await execute_workflow_by_id({}, "wf-1", context)
        return result, budget, create


class TestOnboardingGate:
    async def test_integration_fire_skipped_for_non_onboarded_user(self) -> None:
        result, budget, create = await _run_task(
            _workflow(), _user(completed=False), {"trigger_type": "integration"}
        )
        assert "has not completed onboarding" in result
        budget.assert_not_awaited()
        create.assert_not_awaited()

    async def test_unstamped_trigger_fire_is_recognized_and_skipped(self) -> None:
        """In-flight jobs queued before the trigger service stamped trigger_type
        carry only trigger_data — they must still be treated as system-initiated."""
        result, budget, create = await _run_task(
            _workflow(), _user(completed=False), {"trigger_data": {"event": "x"}}
        )
        assert "has not completed onboarding" in result
        budget.assert_not_awaited()
        create.assert_not_awaited()

    async def test_schedule_fire_skipped_for_non_onboarded_user(self) -> None:
        result, budget, _ = await _run_task(
            _workflow(), _user(completed=False), {"trigger_type": "schedule"}
        )
        assert "has not completed onboarding" in result
        budget.assert_not_awaited()

    async def test_manual_run_not_gated(self) -> None:
        result, budget, _ = await _run_task(
            _workflow(), _user(completed=False), {"trigger_type": "manual"}
        )
        assert "has not completed onboarding" not in result
        budget.assert_awaited_once()

    async def test_onboarded_user_runs_normally(self) -> None:
        result, budget, create = await _run_task(
            _workflow(), _user(completed=True), {"trigger_type": "integration"}
        )
        assert "has not completed onboarding" not in result
        budget.assert_awaited_once()
        create.assert_awaited_once()
