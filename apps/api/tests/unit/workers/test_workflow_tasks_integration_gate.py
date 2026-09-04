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
from app.models.notification.notification_models import (
    ActionStyle,
    ActionType,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.workflow_models import DeactivationReason, IntegrationRef
from app.workers.tasks.workflow_tasks import (
    _notify_workflow_failed,
    _notify_workflow_paused_for_integrations,
    execute_workflow_by_id,
)

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
GMAIL_AND_NOTION = [*GMAIL, IntegrationRef(id="notion", name="Notion")]


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
        assert notify.await_args.args[0].content.body == (
            "'Morning roadmap digest' needs Gmail, which isn't connected. "
            "It's paused and will run again once you reconnect."
        )

    async def test_the_skip_reason_names_every_integration_the_fire_lacked(self) -> None:
        """The reason is the run's only record of why nothing happened; a fire
        that named one of two missing integrations sends the operator after the
        wrong one."""
        result, _, _, _ = await _run_task(
            _workflow(), GMAIL_AND_NOTION, {"trigger_type": "schedule"}
        )

        assert result == "Workflow wf-1 paused — not connected: gmail, notion"

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


class TestTheNoticeTellsTheUserWhatToReconnect:
    """The pause is only useful if the notice is actionable: the workflow that
    stopped, the integration that stopped it, and one click to fix it. These
    pin the copy and the link, because a notice that says the right thing about
    the wrong integration is the loop it was written to end."""

    @staticmethod
    async def _sent(missing: list[IntegrationRef]) -> Any:
        with patch(
            f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock
        ) as notify:
            await _notify_workflow_paused_for_integrations(_workflow(), missing)
        return notify.await_args.args[0]

    async def test_it_names_the_workflow_and_every_integration_it_waits_on(self) -> None:
        request = await self._sent(GMAIL_AND_NOTION)

        assert request.content.title == "Workflow Paused: Morning roadmap digest"
        assert request.content.body == (
            "'Morning roadmap digest' needs Gmail, Notion, which isn't connected. "
            "It's paused and will run again once you reconnect."
        )

    async def test_the_button_connects_the_first_missing_integration_in_place(self) -> None:
        request = await self._sent(GMAIL_AND_NOTION)

        (action,) = request.content.actions
        assert action.label == "Connect Gmail"
        assert action.type == ActionType.REDIRECT
        assert action.style == ActionStyle.PRIMARY
        assert action.config.redirect.url == "/integrations?id=gmail"
        assert action.config.redirect.open_in_new_tab is False
        assert action.config.redirect.close_notification is True

    async def test_it_reaches_this_user_as_an_integration_warning(self) -> None:
        request = await self._sent(GMAIL_AND_NOTION)

        assert request.user_id == "user-1"
        assert request.source == NotificationSourceEnum.INTEGRATION_EXPIRED
        assert request.type == NotificationType.WARNING
        assert request.metadata == {
            "workflow_id": "wf-1",
            "missing_integrations": "gmail,notion",
        }

    async def test_a_notice_that_cannot_be_delivered_is_recorded_not_raised(self) -> None:
        """The workflow is already paused; turning a lost message into a worker
        error would retry the whole fire for nothing."""
        with (
            patch(
                f"{MODULE}.notification_service.create_notification",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await _notify_workflow_paused_for_integrations(_workflow(), GMAIL)

        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.args == (
            "[WORKER] Could not send the integration-paused notice",
        )
        assert mock_log.warning.call_args.kwargs == {
            "workflow_id": "wf-1",
            "error": "mongo down",
            "error_type": "RuntimeError",
        }


class TestTheLimitNoticeIsClaimedPerWorkflow:
    async def test_the_claim_is_made_for_this_workflow_and_its_owner(self) -> None:
        """The claim is a SET NX per workflow: keyed on the wrong id it would
        silence a different workflow's first notice, and keyed on the wrong user
        it would silence everyone's."""
        with (
            patch(
                f"{MODULE}.workflow_repository.claim_limit_notice",
                new_callable=AsyncMock,
                return_value=True,
            ) as claim,
            patch(f"{MODULE}.notification_service.create_notification", new_callable=AsyncMock),
        ):
            await _notify_workflow_failed(
                RateLimitExceededException(feature="trigger_workflow_executions"),
                _workflow(user_id="user-9"),
            )

        claim.assert_awaited_once_with("user-9", "wf-1")
