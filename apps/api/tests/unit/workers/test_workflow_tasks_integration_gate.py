"""The fire-time integration gate, and the day's one limit notice.

186 of 649 bot messages in a 63-conversation production sample named a missing
integration, and 14 threads carried three or more identical ones (one carried
22, then six rate-limit messages). Both loops come from the same place: a
scheduled workflow whose required integration is gone keeps firing, and every
fire mints another message. Pausing on the first such fire, and letting the
limit wall speak once per day, is what turns a message per occurrence into
one message.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.models.scheduler_models import DeactivationReason
from app.models.user_models import UserDocument
from app.models.workflow_models import IntegrationRef
from app.services.outbox.models import Initiative, NoticeOutcome, ProducerKind, SubjectKind
from app.workers.tasks.workflow_tasks import (
    _notify_workflow_failed,
    _notify_workflow_paused_for_integrations,
    execute_workflow_by_id,
)

MODULE = "app.workers.tasks.workflow_tasks"
PAUSE_MODULE = "app.services.workflow.integration_pause"


def _workflow(user_id: str = "6812f0b3c9a14e2b7d5a91cc") -> MagicMock:
    wf = MagicMock()
    wf.id = "wf-1"
    wf.user_id = user_id
    wf.title = "Morning roadmap digest"
    wf.steps = []
    wf.repeat = None
    wf.activated = True
    return wf


async def _run_task(
    workflow: MagicMock,
    missing: list[IntegrationRef],
    context: dict[str, Any] | None,
    *,
    notice_error: Exception | None = None,
) -> tuple[str, AsyncMock, AsyncMock, AsyncMock]:
    onboarded = UserDocument.model_validate({"onboarding": {"completed": True}})

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
        patch(f"{MODULE}.submit", new_callable=AsyncMock, side_effect=notice_error) as notify,
        patch(f"{MODULE}.enforce_cost_budget", new_callable=AsyncMock) as budget,
        patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
        patch(
            f"{MODULE}.execute_workflow_as_chat",
            new_callable=AsyncMock,
            return_value=("conv-1", []),
        ),
        patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        patch(f"{MODULE}.capture"),
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
        assert (
            deactivate.await_args.kwargs["reason"] == DeactivationReason.INTEGRATION_NEVER_CONNECTED
        )
        # No run, so no spend and no agent turn to nag from.
        budget.assert_not_awaited()

    async def test_the_pause_sends_exactly_one_notice(self) -> None:
        _, _, notify, _ = await _run_task(_workflow(), GMAIL, {"trigger_type": "schedule"})

        assert notify.await_count == 1
        assert notify.await_args.args[0].facts == [
            "'Morning roadmap digest' needs Gmail, which isn't connected.",
            "It is paused and will run again once the user reconnects.",
        ]

    async def test_the_skip_reason_names_every_integration_the_fire_lacked(self) -> None:
        """The skip reason is the run's only record; naming one of two missing integrations misdirects."""
        result, _, _, _ = await _run_task(
            _workflow(), GMAIL_AND_NOTION, {"trigger_type": "schedule"}
        )

        assert result == "Workflow wf-1 paused — not connected: gmail, notion"

    async def test_a_trigger_fire_is_gated_too(self) -> None:
        """An integration-triggered workflow whose integration died must be gated too, or it nags every event."""
        result, deactivate, _, _ = await _run_task(
            _workflow(), GMAIL, {"trigger_type": "integration"}
        )

        assert "not connected" in result
        deactivate.assert_awaited_once()

    async def test_a_manual_run_is_not_paused(self) -> None:
        """A manual run gets the connect card in chat instead of a surprise pause — one card is not a loop."""
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


class TestTheLimitNoticeSpeaksOncePerDay:
    async def _filed(self, error: Exception, execution_id: str | None = "exec-1") -> AsyncMock:
        with patch(f"{MODULE}.submit", new_callable=AsyncMock) as notify:
            await _notify_workflow_failed(error, _workflow(), execution_id)
        return notify

    async def test_every_fire_that_hits_the_wall_files_the_one_notice_of_the_day(self) -> None:
        """The report id names the wall's day, so the outbox keeps the repeats to one; no gate sits before the submit."""
        error = RateLimitExceededException(feature="trigger_workflow_executions")

        first = await self._filed(error, "exec-1")
        second = await self._filed(error, "exec-2")

        first_id = first.await_args.args[0].report_id
        assert first_id == second.await_args.args[0].report_id
        assert first_id.startswith("sys:workflow_failed:wf-1:")

    async def test_a_wall_notice_that_cannot_be_filed_raises_and_the_next_fire_files_it(
        self,
    ) -> None:
        """Regression: a SET NX claimed before the submit lost the day's notice when the submit failed."""
        error = RateLimitExceededException(feature="trigger_workflow_executions")
        with patch(f"{MODULE}.submit", new_callable=AsyncMock, side_effect=RuntimeError("down")):
            with pytest.raises(RuntimeError, match="down"):
                await _notify_workflow_failed(error, _workflow(), None)

        retried = await self._filed(error, None)

        retried.assert_awaited_once()


class TestAFailureIsNamedByTheRunItBelongsTo:
    async def test_redelivering_one_failed_run_files_one_notice(self) -> None:
        """Regression: the key was the wall clock, so each redelivery of one run's failure filed another notice."""
        error = RuntimeError("boom")
        with patch(f"{MODULE}.submit", new_callable=AsyncMock) as notify:
            await _notify_workflow_failed(error, _workflow(), "exec-1")
            await _notify_workflow_failed(error, _workflow(), "exec-1")
            await _notify_workflow_failed(error, _workflow(), "exec-2")

        first, again, other = (c.args[0].report_id for c in notify.await_args_list)
        assert first == again == "sys:workflow_failed:wf-1:exec-1"
        assert other == "sys:workflow_failed:wf-1:exec-2"


class TestTheNoticeTellsTheUserWhatToReconnect:
    """The pause notice must be actionable: which workflow and which integrations it waits on.

    These pin the facts, because a notice naming the wrong integration is the loop it was written
    to end.
    """

    @staticmethod
    async def _filed(missing: list[IntegrationRef]) -> Any:
        with patch(f"{MODULE}.submit", new_callable=AsyncMock) as submit:
            await _notify_workflow_paused_for_integrations(_workflow(), missing)
        return submit.await_args.args[0]

    async def test_it_names_the_workflow_and_every_integration_it_waits_on(self) -> None:
        notice = await self._filed(GMAIL_AND_NOTION)

        assert notice.subject.label == "Morning roadmap digest"
        assert notice.facts == [
            "'Morning roadmap digest' needs Gmail, Notion, which isn't connected.",
            "It is paused and will run again once the user reconnects.",
        ]

    async def test_it_reaches_this_user_as_a_workflow_notice_that_needs_them(self) -> None:
        notice = await self._filed(GMAIL_AND_NOTION)

        assert notice.recipient == "6812f0b3c9a14e2b7d5a91cc"
        assert notice.producer is ProducerKind.WORKFLOW
        assert notice.subject.kind is SubjectKind.WORKFLOW_RUN
        assert notice.outcome is NoticeOutcome.NEEDS_YOU
        assert notice.initiative is Initiative.USER_SCHEDULED
        assert notice.report_id.startswith("sys:workflow_paused:wf-1:gmail,notion:")

    async def test_a_notice_that_cannot_be_filed_raises(self) -> None:
        """Regression: the notice was best-effort, so a failed submit left the workflow paused with the user never told."""
        with patch(f"{MODULE}.submit", new_callable=AsyncMock, side_effect=RuntimeError("down")):
            with pytest.raises(RuntimeError, match="down"):
                await _notify_workflow_paused_for_integrations(_workflow(), GMAIL)


class TestThePauseWaitsForItsNotice:
    async def test_a_notice_that_cannot_be_filed_leaves_the_workflow_unpaused(self) -> None:
        """Regression: pausing first and filing second left a silent pause whenever the filing failed."""
        _, deactivate, _, _ = await _run_task(
            _workflow(), GMAIL, {"trigger_type": "schedule"}, notice_error=RuntimeError("down")
        )

        deactivate.assert_not_awaited()
