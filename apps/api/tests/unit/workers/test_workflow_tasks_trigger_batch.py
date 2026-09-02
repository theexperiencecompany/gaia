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
    context: dict[str, Any] | None,
    drained: list[dict[str, Any]],
    budget_error: Exception | None = None,
) -> tuple[str, AsyncMock, AsyncMock, AsyncMock, Any, Any, Any]:
    with (
        patch(f"{MODULE}.workflow_scheduler") as scheduler,
        patch(
            f"{MODULE}.user_repository.get", new_callable=AsyncMock, return_value=_onboarded_user()
        ),
        patch(
            f"{MODULE}.drain_trigger_batch", new_callable=AsyncMock, return_value=drained
        ) as drain,
        patch(
            f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock, side_effect=budget_error
        ),
        patch(f"{MODULE}.reschedule_if_refilled", new_callable=AsyncMock) as refill,
        patch(f"{MODULE}.coalesce_window_seconds", return_value=900) as coalesce,
        patch(f"{MODULE}.notification_service", MagicMock(send_notification=AsyncMock())),
        patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
        patch(
            f"{MODULE}.execute_workflow_as_chat",
            new_callable=AsyncMock,
            return_value=("conv-1", []),
        ) as run_chat,
        patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event"),
    ):
        workflow = _workflow()
        scheduler.get_task = AsyncMock(return_value=workflow)
        scheduler.claim_task_for_execution = AsyncMock(return_value=True)
        scheduler.handle_recurring_task = AsyncMock()
        create.return_value = MagicMock(execution_id="exec-1")
        with patch(f"{MODULE}.log") as log_mock:
            result = await execute_workflow_by_id({}, "wf-1", context)
        return result, drain, run_chat, refill, log_mock, coalesce, workflow


class TestTriggerBatchDrain:
    async def test_whole_batch_reaches_the_agent_as_one_run(self) -> None:
        events = [{"id": index} for index in range(12)]
        result, drain, run_chat, refill, log_mock, coalesce, workflow = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"}, events
        )

        assert result == "Workflow wf-1 executed successfully"
        drain.assert_awaited_once_with("trigger_batch:wf-1")
        run_chat.assert_awaited_once()
        context = run_chat.await_args.args[2]
        assert context["trigger_data"]["count"] == 12
        assert context["trigger_data"]["events"] == events
        # The wide event carries the batch size — how a burst is audited later.
        log_mock.set_ns.assert_any_call("workflow", trigger_batch_size=12)
        # Events that landed mid-run get their follow-up on the workflow's window.
        refill.assert_awaited_once()
        wf_id, batch_key, window_seconds, refill_context = refill.await_args.args
        assert (wf_id, batch_key, window_seconds) == ("wf-1", "trigger_batch:wf-1", 900)
        assert refill_context["trigger_type"] == "integration"
        # The refill window must be derived from THIS workflow's trigger config,
        # not a default the mock happens to return for anything.
        coalesce.assert_called_once_with(workflow.trigger_config)

    async def test_empty_batch_skips_the_run_entirely(self) -> None:
        """Another run already drained these events — executing again would
        spend the user's budget re-processing nothing."""
        result, _drain, run_chat, refill, log_mock, _coalesce, _wf = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"}, []
        )

        assert result == "Workflow wf-1 skipped — trigger batch empty"
        log_mock.set_ns.assert_any_call("workflow", outcome="trigger_batch_empty")
        run_chat.assert_not_awaited()
        # Even a skipped run held the job id — mid-run arrivals still get
        # their follow-up.
        refill.assert_awaited_once()

    async def test_unbatched_run_never_touches_the_buffer(self) -> None:
        result, drain, run_chat, refill, _log, _coalesce, _wf = await _run_task(
            {"trigger_type": "manual"}, [{"id": 1}]
        )

        assert result == "Workflow wf-1 executed successfully"
        drain.assert_not_awaited()
        refill.assert_not_awaited()
        assert "trigger_data" not in run_chat.await_args.args[2]


class TestGatesRunBeforeTheDrain:
    async def test_budget_walled_run_leaves_the_buffer_intact(self) -> None:
        """A rejected run must not consume the batch — the events belong to a
        future run after the budget resets, not to the void."""
        result, drain, run_chat, _refill, _log, _coalesce, _wf = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
            [{"id": 1}],
            budget_error=RuntimeError("daily budget exhausted"),
        )

        drain.assert_not_awaited()
        run_chat.assert_not_awaited()


class TestRefillOnEveryExit:
    async def test_a_budget_walled_run_still_reschedules_refill_arrivals(self) -> None:
        """Events that land while a gate-rejected run holds the job id would be
        stranded without the finally — a failed run must strand them no more
        than a successful one."""
        result, _drain, _run_chat, refill, _log, _coalesce, _wf = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
            [{"id": 1}],
            budget_error=RuntimeError("daily budget exhausted"),
        )

        refill.assert_awaited_once()
        wf_id, batch_key, window_seconds, _context = refill.await_args.args
        assert (wf_id, batch_key, window_seconds) == ("wf-1", "trigger_batch:wf-1", 900)

    async def test_a_refill_scheduling_error_never_masks_the_run_result(self) -> None:
        """The finally is best-effort: a Redis blip while scheduling the
        follow-up must not turn a successful run into a failure."""
        events = [{"id": 1}]
        with patch(
            f"{MODULE}.reschedule_if_refilled",
            new_callable=AsyncMock,
            side_effect=RuntimeError("redis blip"),
        ) as broken_refill:
            with (
                patch(f"{MODULE}.workflow_scheduler") as scheduler,
                patch(
                    f"{MODULE}.user_repository.get",
                    new_callable=AsyncMock,
                    return_value=_onboarded_user(),
                ),
                patch(f"{MODULE}.drain_trigger_batch", new_callable=AsyncMock, return_value=events),
                patch(f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock),
                patch(f"{MODULE}.coalesce_window_seconds", return_value=900),
                patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
                patch(
                    f"{MODULE}.execute_workflow_as_chat",
                    new_callable=AsyncMock,
                    return_value=("conv-1", []),
                ),
                patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
                patch(
                    f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock
                ),
                patch(f"{MODULE}.capture_event"),
                patch(f"{MODULE}.log") as log_mock,
            ):
                scheduler.get_task = AsyncMock(return_value=_workflow())
                scheduler.claim_task_for_execution = AsyncMock(return_value=True)
                scheduler.handle_recurring_task = AsyncMock()
                create.return_value = MagicMock(execution_id="exec-1")
                result = await execute_workflow_by_id(
                    {},
                    "wf-1",
                    {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
                )

        assert result == "Workflow wf-1 executed successfully"
        broken_refill.assert_awaited_once()
        log_mock.warning.assert_any_call(
            "[WORKER] Trigger batch refill check failed",
            workflow_id="wf-1",
            error="redis blip",
            error_type="RuntimeError",
        )

    async def test_a_run_with_no_context_never_touches_batching(self) -> None:
        """Scheduled fires pass no context at all — nothing batch-shaped may
        run for them, including the finally's refill check."""
        result, drain, _run_chat, refill, _log, coalesce, _wf = await _run_task(None, [])

        assert result == "Workflow wf-1 executed successfully"
        drain.assert_not_awaited()
        refill.assert_not_awaited()
        coalesce.assert_not_called()


class TestDrainUnavailable:
    async def test_redis_down_at_drain_never_claims_the_batch_was_empty(self) -> None:
        """None from the drain means "could not look" — the run must exit
        without consuming, and the finally still schedules the follow-up."""
        result, drain, run_chat, refill, log_mock, _coalesce, _wf = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
            None,  # drain_trigger_batch returns None
        )

        assert result == "Workflow wf-1 skipped — trigger batch unavailable"
        log_mock.set_ns.assert_any_call("workflow", outcome="trigger_batch_unavailable")
        run_chat.assert_not_awaited()
        refill.assert_awaited_once()
