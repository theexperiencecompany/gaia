"""The batched-trigger path in execute_workflow_by_id.

A coalesced run carries its events in Redis, not in the job payload — that is
what let concurrent enqueues dedup down to one job. The task must collect them
and hand the agent the whole batch, and must not run at all when another run
already took them.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.tasks.workflow_tasks import execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"


def _workflow() -> MagicMock:
    wf = MagicMock()
    wf.user_id = "user-1"
    wf.steps = []
    wf.repeat = None
    wf.activated = True
    return wf


def _onboarded_user() -> MagicMock:
    user = MagicMock()
    user.onboarding = {"completed": True}
    return user


async def _run_task(
    context: dict[str, Any] | None, drained: list[dict[str, Any]]
) -> tuple[str, AsyncMock, AsyncMock]:
    with (
        patch(f"{MODULE}.workflow_scheduler") as scheduler,
        patch(
            f"{MODULE}.user_repository.get", new_callable=AsyncMock, return_value=_onboarded_user()
        ),
        patch(
            f"{MODULE}.drain_trigger_batch", new_callable=AsyncMock, return_value=drained
        ) as drain,
        patch(f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock),
        patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
        patch(
            f"{MODULE}.execute_workflow_as_chat", new_callable=AsyncMock, return_value="conv-1"
        ) as run_chat,
        patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event"),
    ):
        scheduler.get_task = AsyncMock(return_value=_workflow())
        scheduler.claim_scheduled_for_execution = AsyncMock(return_value=True)
        scheduler.handle_recurring_task = AsyncMock()
        create.return_value = MagicMock(execution_id="exec-1")
        result = await execute_workflow_by_id({}, "wf-1", context)
        return result, drain, run_chat


class TestTriggerBatchDrain:
    async def test_whole_batch_reaches_the_agent_as_one_run(self) -> None:
        events = [{"id": index} for index in range(12)]
        result, drain, run_chat = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"}, events
        )

        assert "executed successfully" in result
        drain.assert_awaited_once_with("trigger_batch:wf-1")
        run_chat.assert_awaited_once()
        context = run_chat.await_args.args[2]
        assert context["trigger_data"]["count"] == 12
        assert context["trigger_data"]["events"] == events

    async def test_empty_batch_skips_the_run_entirely(self) -> None:
        """Another run already drained these events — executing again would
        spend the user's budget re-processing nothing."""
        result, _drain, run_chat = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"}, []
        )

        assert "trigger batch empty" in result
        run_chat.assert_not_awaited()

    async def test_unbatched_run_never_touches_the_buffer(self) -> None:
        result, drain, run_chat = await _run_task({"trigger_type": "manual"}, [{"id": 1}])

        assert "executed successfully" in result
        drain.assert_not_awaited()
        assert "trigger_data" not in run_chat.await_args.args[2]
