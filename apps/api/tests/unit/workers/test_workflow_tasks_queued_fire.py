"""A workflow fire whose executor dispatch was QUEUED must not record success.

One executor runs per conversation. A workflow whose agentic run takes longer
than its own cron period fires again while the previous run still holds that
conversation's busy lock, so ``call_executor`` puts the new fire on the queue
and answers with an acknowledgement instead of running anything. The comms agent
treats that acknowledgement as its result and the fire completed in ~15s with
``status="success"``, ``summary="Workflow executed"`` and a trace holding one
``call_executor`` call — with a */5 cron over a five-minute run, EVERY record
after the first was a fake success, and the record the next run reads as its own
history said the workflow had done its job.

These tests drive the real ``execute_workflow_by_id`` → ``_run_workflow`` →
``execute_workflow_as_chat`` path with only its I/O edges mocked, so the queued
outcome is decided by the production code, not by the harness.
"""

import asyncio
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from app.constants.log_tags import LogTag
from app.models.agent_models import SilentRunResult
from app.models.playbook_models import PlaybookRunStatus
from app.models.workflow_models import TriggerType
from app.services.analytics_service import AnalyticsEvents
from app.services.workflow.conversation_service import build_selected_workflow_data
from app.services.workflow.execution_service import WorkflowFireTimedOut
from app.workers.config.worker_settings import WORKER_JOB_TIMEOUT_SECONDS
from app.workers.tasks.workflow_tasks import (
    AGENT_RUN_SUMMARY,
    QUEUED_MESSAGE,
    execute_workflow_by_id,
)

MODULE = "app.workers.tasks.workflow_tasks"

QUEUED_TASK_ID = "8f0c2a44-queued"


def _workflow() -> MagicMock:
    workflow = MagicMock()
    workflow.id = str(uuid4())
    workflow.user_id = "user_abc"
    workflow.title = "Inbox triage"
    workflow.description = "Triage the inbox every five minutes"
    workflow.prompt = "Triage the inbox"
    workflow.steps = [MagicMock(id="s1", title="Read mail", description="", category="comms")]
    workflow.notify_on_completion = True
    workflow.repeat = True
    workflow.activated = True
    workflow.occurrence_count = 0
    return workflow


class _Harness:
    """Every I/O edge around one fire, mocked. The fire itself is real."""

    def __init__(self, workflow: MagicMock, *, queued_task_id: str | None) -> None:
        self.workflow = workflow
        self.scheduler = AsyncMock()
        self.scheduler.get_task = AsyncMock(return_value=workflow)
        self.execution = MagicMock()
        self.execution.execution_id = "exec_1"
        self.complete_execution = AsyncMock()
        self.increment = AsyncMock()
        self.capture_event = MagicMock()
        self.notify = AsyncMock()
        self.record_run_outcome = AsyncMock(return_value=None)
        self.cost_budget = AsyncMock()
        self.add_messages = AsyncMock()
        self.reset_threads = AsyncMock()
        self.conversation = AsyncMock(return_value="conv_1")
        self.get_user = AsyncMock(return_value={"user_id": workflow.user_id, "timezone": "UTC"})
        self.log = MagicMock()
        self.agent = AsyncMock(
            return_value=SilentRunResult(
                message="I'm on it — I'll handle that right after the current task.",
                tool_data={},
                queued_task_id=queued_task_id,
            )
        )

    def workflow_event(self) -> dict[str, object]:
        """The merged ``workflow`` wide-event namespace this fire stamped.

        Production can only tell a queued fire from a real one by this
        namespace, so it is asserted as a contract, not as incidental logging.
        """
        merged: dict[str, object] = {}
        for entry in self.log.set_ns.call_args_list:
            if entry.args and entry.args[0] == "workflow":
                merged.update(entry.kwargs)
        return merged

    def patches(self) -> list:
        onboarded = MagicMock()
        onboarded.onboarding = {"completed": True}
        return [
            patch(f"{MODULE}.workflow_scheduler", self.scheduler),
            patch(f"{MODULE}.create_execution", AsyncMock(return_value=self.execution)),
            patch(f"{MODULE}.complete_execution", self.complete_execution),
            patch(
                f"{MODULE}.WorkflowService",
                MagicMock(increment_execution_count=self.increment),
            ),
            patch(f"{MODULE}.capture_event", self.capture_event),
            patch(f"{MODULE}.enforce_daily_cost_budget", self.cost_budget),
            patch(f"{MODULE}.notification_service.create_notification", self.notify),
            patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=onboarded)),
            # ``playbook_repository.get_for_workflow`` is already pinned to None
            # by the autouse fixture in tests/unit/workers/conftest.py, so this
            # fire takes the agent path.
            patch(f"{MODULE}.get_user_by_id", self.get_user),
            patch(f"{MODULE}.get_or_create_workflow_conversation", self.conversation),
            patch(f"{MODULE}.add_workflow_execution_messages", self.add_messages),
            patch(f"{MODULE}.reset_workflow_threads", self.reset_threads),
            patch(
                f"{MODULE}.playbook_repository.record_run_outcome",
                self.record_run_outcome,
            ),
            patch("app.agents.core.agent.call_agent_silent", self.agent),
            patch(f"{MODULE}.log", self.log),
        ]


async def _fire(harness: _Harness) -> str:
    with ExitStack() as stack:
        for patcher in harness.patches():
            stack.enter_context(patcher)
        return await execute_workflow_by_id(
            {},
            harness.workflow.id,
            # The production shape of the bug: a cron whose period is shorter
            # than its own run, so every fire after the first lands on a busy
            # conversation.
            {
                "trigger_type": TriggerType.SCHEDULE.value,
                "scheduled_for": datetime.now(UTC).timestamp(),
            },
        )


async def test_a_queued_fire_is_not_recorded_as_a_successful_execution() -> None:
    """The regression: nothing ran, so the record must not say the workflow did."""
    harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

    await _fire(harness)

    harness.complete_execution.assert_awaited_once()
    kwargs = harness.complete_execution.await_args.kwargs
    assert kwargs["status"] != "success"
    assert kwargs.get("summary") != AGENT_RUN_SUMMARY


async def test_a_queued_fire_records_why_it_did_not_run_in_plain_words() -> None:
    """The record is read by the workflow's owner: what happened and what to
    change, no task ids (those go to the log)."""
    harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

    await _fire(harness)

    kwargs = harness.complete_execution.await_args.kwargs
    assert kwargs["status"] == "failed"
    error_message = kwargs["error_message"]
    assert error_message == QUEUED_MESSAGE
    assert QUEUED_TASK_ID not in error_message


async def test_a_queued_fire_is_not_counted_as_a_successful_run() -> None:
    """A fake success also inflated the workflow's own statistics and analytics."""
    harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

    await _fire(harness)

    for entry in harness.increment.await_args_list:
        assert entry.kwargs.get("is_successful") is not True
    captured = [entry.args[1] for entry in harness.capture_event.call_args_list if entry.args]
    assert AnalyticsEvents.WORKFLOW_EXECUTED not in captured


async def test_a_queued_fire_notifies_the_user_of_nothing() -> None:
    """No 'done' and no 'failed': the queued task still runs and reports itself.

    Telling the user their workflow finished is the user-visible half of the
    lie; telling them it broke would be a second one, since nothing broke.
    """
    harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

    await _fire(harness)

    harness.notify.assert_not_awaited()


async def test_a_queued_fire_is_visible_on_the_wide_event() -> None:
    """Production cannot count queued fires unless the fire says it was one."""
    harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

    await _fire(harness)

    event = harness.workflow_event()
    assert event.get("queued") is True
    assert event.get("queued_task_id") == QUEUED_TASK_ID


async def test_a_queued_fire_still_arms_the_next_occurrence() -> None:
    """A fire that could not run must not silently kill the recurring schedule."""
    harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

    await _fire(harness)

    harness.scheduler.handle_recurring_task.assert_awaited_once()


async def test_a_fire_whose_executor_actually_ran_still_records_success() -> None:
    """The control: the fix must only bite when the dispatch was queued."""
    harness = _Harness(_workflow(), queued_task_id=None)

    result = await _fire(harness)

    assert "executed successfully" in result
    kwargs = harness.complete_execution.await_args.kwargs
    assert kwargs["status"] == "success"
    assert kwargs["summary"] == AGENT_RUN_SUMMARY
    harness.increment.assert_awaited_once()
    assert harness.increment.await_args.kwargs["is_successful"] is True


#: A fixed occurrence stamp, so the claim the fire makes is assertable.
SCHEDULED_FOR = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)


async def _fire_at_a_fixed_occurrence(harness: _Harness) -> str:
    """The same scheduled fire as ``_fire``, pinned to a known occurrence."""
    with ExitStack() as stack:
        for patcher in harness.patches():
            stack.enter_context(patcher)
        return await execute_workflow_by_id(
            {},
            harness.workflow.id,
            {
                "trigger_type": TriggerType.SCHEDULE.value,
                "scheduled_for": SCHEDULED_FOR.timestamp(),
            },
        )


class TestAQueuedFiresBookkeepingIsAddressedCorrectly:
    """The record, the counter and the log line each carry an id. A fire that
    books itself against the wrong workflow, user or task is worse than one
    that books nothing: it is wrong data nobody goes looking for."""

    async def test_the_event_says_the_fire_was_queued_in_the_words_production_greps_for(
        self,
    ) -> None:
        harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

        await _fire(harness)

        assert harness.workflow_event()["outcome"] == "queued_behind_in_flight_run"

    async def test_the_log_names_the_workflow_and_the_task_that_took_the_work(
        self,
    ) -> None:
        harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

        await _fire(harness)

        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Workflow fire queued behind its previous run — nothing executed",
            workflow_id=harness.workflow.id,
            queued_task_id=QUEUED_TASK_ID,
        )

    async def test_the_record_closed_is_this_fires_own_and_points_at_the_conversation(
        self,
    ) -> None:
        harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

        await _fire(harness)

        assert harness.complete_execution.await_args_list == [
            call(
                execution_id="exec_1",
                status="failed",
                error_message=QUEUED_MESSAGE,
                conversation_id="conv_1",
                trace=[],
            )
        ]

    async def test_the_failure_is_counted_against_this_workflow_for_this_user(
        self,
    ) -> None:
        harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)

        await _fire(harness)

        assert harness.increment.await_args_list == [
            call(harness.workflow.id, harness.workflow.user_id, is_successful=False)
        ]

    async def test_a_rearm_failure_names_the_workflow_it_could_not_arm(self) -> None:
        """Without the id, the error line cannot be traced to a schedule that
        has silently stopped advancing."""
        harness = _Harness(_workflow(), queued_task_id=QUEUED_TASK_ID)
        harness.scheduler.handle_recurring_task = AsyncMock(side_effect=RuntimeError("redis away"))

        await _fire(harness)

        logged = [str(entry.args[0]) for entry in harness.log.error.call_args_list if entry.args]
        assert any(harness.workflow.id in line for line in logged), logged


class TestASuccessfulFiresBookkeepingIsAddressedCorrectly:
    async def test_the_success_is_counted_against_this_workflow_for_this_user(
        self,
    ) -> None:
        harness = _Harness(_workflow(), queued_task_id=None)

        await _fire(harness)

        assert harness.increment.await_args_list == [
            call(harness.workflow.id, harness.workflow.user_id, is_successful=True)
        ]

    async def test_the_fire_is_processed_and_logged_under_the_id_it_was_asked_for(
        self,
    ) -> None:
        harness = _Harness(_workflow(), queued_task_id=None)

        result = await _fire(harness)

        harness.scheduler.get_task.assert_awaited_once_with(harness.workflow.id)
        harness.log.info.assert_any_call(
            f"{LogTag.WORKER} Processing workflow execution",
            workflow_id=harness.workflow.id,
        )
        assert "executed successfully" in result

    async def test_the_daily_cost_wall_is_checked_for_this_user_and_this_feature(
        self,
    ) -> None:
        """The wall runs before any record or LLM work; a blank user or feature
        key would let a spent budget through."""
        harness = _Harness(_workflow(), queued_task_id=None)

        await _fire(harness)

        assert harness.cost_budget.await_args_list == [
            call(harness.workflow.user_id, feature_key="trigger_workflow_executions")
        ]

    async def test_a_scheduled_fire_claims_the_occurrence_it_was_armed_for(
        self,
    ) -> None:
        """ARQ cannot cancel a deferred job, so the claim is pinned to the
        occurrence — an unpinned claim runs a workflow at a time it was
        rescheduled away from."""
        harness = _Harness(_workflow(), queued_task_id=None)

        await _fire_at_a_fixed_occurrence(harness)

        assert harness.scheduler.claim_task_for_execution.await_args_list == [
            call(harness.workflow.id, expected_occurrence=SCHEDULED_FOR)
        ]

    async def test_a_background_completion_is_captured_under_its_real_trigger_type(
        self,
    ) -> None:
        """The run-now endpoint captures manual fires itself; only background
        origins are captured here, and only with the type they actually had."""
        harness = _Harness(_workflow(), queued_task_id=None)

        await _fire(harness)

        harness.capture_event.assert_any_call(
            harness.workflow.user_id,
            AnalyticsEvents.WORKFLOW_EXECUTED,
            {
                "workflow_id": harness.workflow.id,
                "trigger_type": TriggerType.SCHEDULE.value,
            },
        )

    async def test_a_fire_far_off_its_scheduled_time_is_warned_about_with_its_drift(
        self,
    ) -> None:
        workflow = _workflow()
        workflow.scheduled_at = datetime.now(UTC) - timedelta(hours=1)
        harness = _Harness(workflow, queued_task_id=None)

        await _fire(harness)

        drift = [
            entry
            for entry in harness.log.warning.call_args_list
            if entry.args and "fired off schedule" in str(entry.args[0])
        ]
        assert len(drift) == 1
        assert drift[0].kwargs["workflow_id"] == workflow.id
        assert drift[0].kwargs["drift"] >= 3600


class TestTheChatRunPersistsTheTriggerTurnItself:
    """The trigger turn is what the UI renders as the workflow card; the result
    is saved by the delivery path, so this turn is all this function writes."""

    async def test_the_run_announces_itself_under_the_workflow_and_user_it_runs_for(
        self,
    ) -> None:
        harness = _Harness(_workflow(), queued_task_id=None)

        await _fire(harness)

        harness.log.info.assert_any_call(
            f"{LogTag.WORKER} Executing workflow as chat session",
            workflow_id=harness.workflow.id,
            user_id=harness.workflow.user_id,
        )
        harness.log.set.assert_any_call(conversation_context_found=True)

    async def test_the_conversations_checkpoint_threads_are_reset_before_the_run(
        self,
    ) -> None:
        """Without the reset the run replays every previous run out of the
        checkpoints instead of reading this fire's recorded trace."""
        harness = _Harness(_workflow(), queued_task_id=None)

        await _fire(harness)

        harness.reset_threads.assert_awaited_once_with("conv_1")

    async def test_the_trigger_turn_is_an_empty_user_message_carrying_the_workflow_card(
        self,
    ) -> None:
        harness = _Harness(_workflow(), queued_task_id=None)

        await _fire(harness)

        sent = harness.add_messages.await_args
        assert sent.kwargs["conversation_id"] == "conv_1"
        assert sent.kwargs["user_id"] == harness.workflow.user_id
        (message,) = sent.kwargs["workflow_execution_messages"]
        assert message.type == "user"
        # Empty on purpose: the UI renders the card, not a "Run workflow: ..." bubble.
        assert message.response == ""
        assert message.selectedWorkflow == build_selected_workflow_data(harness.workflow)
        assert UUID(message.message_id).version == 4


class TestAFireCutOffByTheJobTimeoutIsBookedAgainstTheRightIds:
    """ARQ cancels the job rather than raising into it, so this is the only
    place the fire can be closed — and it has to close the right record."""

    async def test_the_timeout_is_named_recorded_counted_and_rearmed(self) -> None:
        harness = _Harness(_workflow(), queued_task_id=None)
        harness.agent = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await _fire(harness)

        reason = str(WorkflowFireTimedOut(WORKER_JOB_TIMEOUT_SECONDS))
        harness.log.error.assert_any_call(
            f"{LogTag.WORKER} Workflow fire cut off by the job timeout",
            workflow_id=harness.workflow.id,
            error=reason,
            error_type="WorkflowFireTimedOut",
        )
        assert harness.complete_execution.await_args_list == [
            call(
                execution_id="exec_1",
                status="failed",
                error_message=reason,
                conversation_id=None,
                trace=None,
            )
        ]
        assert harness.increment.await_args_list == [
            call(harness.workflow.id, harness.workflow.user_id, is_successful=False)
        ]
        harness.scheduler.handle_recurring_task.assert_awaited_once()

    async def test_the_shortcut_is_marked_failed_for_this_workflow_and_user(
        self,
    ) -> None:
        """Whatever the replay was doing may have run its side effects before
        the cut, so the next fire must heal rather than replay them again."""
        harness = _Harness(_workflow(), queued_task_id=None)
        harness.agent = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await _fire(harness)

        harness.record_run_outcome.assert_awaited_once()
        recorded = harness.record_run_outcome.await_args
        assert recorded.args[0] == harness.workflow.id
        assert recorded.args[1] == harness.workflow.user_id
        assert recorded.args[2].status is PlaybookRunStatus.FAILED
        assert recorded.args[2].reason == str(WorkflowFireTimedOut(WORKER_JOB_TIMEOUT_SECONDS))

    async def test_a_rearm_failure_after_a_timeout_names_the_workflow(self) -> None:
        harness = _Harness(_workflow(), queued_task_id=None)
        harness.agent = AsyncMock(side_effect=asyncio.CancelledError())
        harness.scheduler.handle_recurring_task = AsyncMock(side_effect=RuntimeError("redis away"))

        with pytest.raises(asyncio.CancelledError):
            await _fire(harness)

        logged = [str(entry.args[0]) for entry in harness.log.error.call_args_list if entry.args]
        assert any(harness.workflow.id in line for line in logged), logged
