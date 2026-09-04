"""The fire-time integration gate, and the limit-notice ceiling.

186 of 649 bot messages in a 63-conversation production sample named a missing
integration, and 14 threads carried three or more identical ones (one carried
22, then six rate-limit messages). Both loops come from the same place: a
scheduled workflow whose required integration is gone keeps firing, and every
fire mints another message. Pausing on the first such fire, and letting the
limit wall speak once per window, is what turns a message per occurrence into
one message.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.models.workflow_models import DeactivationReason, IntegrationRef
from app.workers.tasks.workflow_tasks import _notify_workflow_failed, execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"
PAUSE_MODULE = "app.services.workflow.integration_pause"


def _workflow(user_id: str = "user-1") -> MagicMock:
    wf = MagicMock()
    wf.id = "wf-1"
    wf.user_id = user_id
    wf.title = "Morning roadmap digest"
    wf.steps = []
    wf.repeat = None
    wf.activated = True
    return wf


async def _run_task(
    workflow: MagicMock, missing: list[IntegrationRef], context: dict[str, Any] | None
) -> tuple[str, AsyncMock, AsyncMock, AsyncMock]:
    onboarded = MagicMock()
    onboarded.onboarding = {"completed": True}

    with (
        patch(f"{MODULE}.workflow_scheduler") as scheduler,
        patch(f"{MODULE}.user_repository.get", new_callable=AsyncMock, return_value=onboarded),
        patch(
            f"{PAUSE_MODULE}.compute_missing_integrations",
            new_callable=AsyncMock,
            return_value=missing,
        ),
        patch(
            f"{PAUSE_MODULE}.WorkflowService.deactivate_workflow", new_callable=AsyncMock
        ) as deactivate,
        patch(
            f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock
        ) as notify,
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
        return result, deactivate, notify, budget


GMAIL = [IntegrationRef(id="gmail", name="Gmail")]


class TestADisconnectedIntegrationPausesTheWorkflow:
    async def test_a_scheduled_fire_pauses_instead_of_running(self) -> None:
        result, deactivate, _, budget = await _run_task(
            _workflow(), GMAIL, {"trigger_type": "schedule"}
        )

        assert "not connected" in result
        assert deactivate.await_args.kwargs["reason"] == DeactivationReason.INTEGRATION_EXPIRED
        # No run, so no spend and no agent turn to nag from.
        budget.assert_not_awaited()

    async def test_the_pause_sends_exactly_one_notice(self) -> None:
        _, _, notify, _ = await _run_task(_workflow(), GMAIL, {"trigger_type": "schedule"})

        assert notify.await_count == 1
        request = notify.await_args.args[0]
        assert "Gmail" in request.content.body

    async def test_a_trigger_fire_is_gated_too(self) -> None:
        """Composio/email trigger fires reach the same task and repeated just as
        hard — an integration-triggered workflow whose integration died would
        otherwise nag on every inbound event."""
        result, deactivate, _, _ = await _run_task(
            _workflow(), GMAIL, {"trigger_type": "integration"}
        )

        assert "not connected" in result
        deactivate.assert_awaited_once()

    async def test_a_manual_run_is_not_paused(self) -> None:
        """The user is standing there and gets the connect card in chat; pausing
        the workflow they just asked to run would be a surprise, and one card is
        not a loop."""
        result, deactivate, _, budget = await _run_task(
            _workflow(), GMAIL, {"trigger_type": "manual"}
        )

        assert "not connected" not in result
        deactivate.assert_not_awaited()
        budget.assert_awaited_once()

    async def test_a_workflow_with_every_integration_connected_runs(self) -> None:
        result, deactivate, notify, budget = await _run_task(
            _workflow(), [], {"trigger_type": "schedule"}
        )

        assert "not connected" not in result
        deactivate.assert_not_awaited()
        notify.assert_not_awaited()
        budget.assert_awaited_once()


class TestTheLimitNoticeSpeaksOncePerWindow:
    async def _notify(self, already_sent: bool) -> AsyncMock:
        with (
            patch(
                f"{MODULE}.workflow_repository.claim_limit_notice",
                new_callable=AsyncMock,
                return_value=not already_sent,
            ),
            patch(
                f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock
            ) as notify,
        ):
            error = RateLimitExceededException(feature="trigger_workflow_executions")
            await _notify_workflow_failed(error, _workflow())
        return notify

    async def test_the_first_wall_of_the_day_is_reported(self) -> None:
        notify = await self._notify(already_sent=False)

        notify.assert_awaited_once()

    async def test_every_later_fire_that_hits_the_same_wall_stays_quiet(self) -> None:
        notify = await self._notify(already_sent=True)

        notify.assert_not_awaited()
