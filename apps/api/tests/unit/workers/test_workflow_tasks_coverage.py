"""Argument-level coverage for the system-run guards in execute_workflow_by_id.

The onboarding lookup, the daily cost-budget call and the skip-path re-arm are
asserted on the arguments they receive: a call-count-only assertion cannot tell
a correct call from one made for the wrong user, feature or workflow.
"""

from typing import Any, NamedTuple
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.limit_upsell import LimitHitOrigin
from app.workers.tasks.workflow_tasks import execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"


class _Run(NamedTuple):
    result: str
    scheduler: MagicMock
    user_get: AsyncMock
    budget: AsyncMock
    log: MagicMock


def _workflow(user_id: str = "user-1", occurrence_count: int = 2) -> MagicMock:
    wf = MagicMock()
    wf.id = "wf-1"
    wf.user_id = user_id
    wf.steps = []
    wf.repeat = True
    wf.activated = True
    wf.occurrence_count = occurrence_count
    return wf


def _user(completed: bool) -> MagicMock:
    user = MagicMock()
    user.onboarding = {"completed": completed}
    return user


async def _run_task(
    workflow: MagicMock,
    user: MagicMock,
    context: dict[str, Any] | None,
    rearm_error: Exception | None = None,
) -> _Run:
    scheduler = MagicMock()
    scheduler.get_task = AsyncMock(return_value=workflow)
    scheduler.claim_scheduled_for_execution = AsyncMock(return_value=True)
    scheduler.handle_recurring_task = AsyncMock(side_effect=rearm_error)
    user_get = AsyncMock(return_value=user)
    with (
        patch(f"{MODULE}.workflow_scheduler", scheduler),
        patch(f"{MODULE}.user_repository.get", user_get),
        patch(f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock) as budget,
        patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
        patch(f"{MODULE}.execute_workflow_as_chat", new_callable=AsyncMock, return_value="conv-1"),
        patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event"),
        patch(f"{MODULE}.log") as log,
    ):
        create.return_value = MagicMock(execution_id="exec-1")
        result = await execute_workflow_by_id({}, "wf-1", context)
    return _Run(result, scheduler, user_get, budget, log)


class TestSystemRunGuards:
    async def test_onboarding_is_checked_for_the_workflows_owner(self) -> None:
        run = await _run_task(
            _workflow("owner-7"), _user(completed=False), {"trigger_type": "schedule"}
        )
        assert "has not completed onboarding" in run.result
        run.user_get.assert_awaited_once_with("owner-7")

    async def test_budget_enforced_for_owner_on_workflow_execution_feature(self) -> None:
        run = await _run_task(
            _workflow("owner-7"), _user(completed=True), {"trigger_type": "schedule"}
        )
        run.budget.assert_awaited_once_with(
            "owner-7",
            feature_key="trigger_workflow_executions",
            origin=LimitHitOrigin.BACKGROUND,
        )

    async def test_skipped_recurring_workflow_still_arms_next_occurrence(self) -> None:
        workflow = _workflow(occurrence_count=2)
        run = await _run_task(workflow, _user(completed=False), {"trigger_type": "schedule"})
        run.scheduler.handle_recurring_task.assert_awaited_once_with(workflow, 3)

    async def test_rearm_failure_on_skip_names_the_workflow(self) -> None:
        run = await _run_task(
            _workflow(),
            _user(completed=False),
            {"trigger_type": "schedule"},
            rearm_error=RuntimeError("boom"),
        )
        run.log.error.assert_called_once()
        assert "wf-1" in run.log.error.call_args.args[0]
        assert "boom" in run.log.error.call_args.args[0]
