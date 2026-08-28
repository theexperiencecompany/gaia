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

from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.agent_models import SilentRunResult
from app.models.workflow_models import TriggerType
from app.services.analytics_service import AnalyticsEvents
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
        for call in self.log.set_ns.call_args_list:
            if call.args and call.args[0] == "workflow":
                merged.update(call.kwargs)
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
            patch(f"{MODULE}.notification_service.create_notification", self.notify),
            patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=onboarded)),
            # ``playbook_repository.get_for_workflow`` is already pinned to None
            # by the autouse fixture in tests/unit/workers/conftest.py, so this
            # fire takes the agent path.
            patch(
                f"{MODULE}.get_user_by_id",
                AsyncMock(return_value={"user_id": self.workflow.user_id, "timezone": "UTC"}),
            ),
            patch(
                f"{MODULE}.get_or_create_workflow_conversation",
                AsyncMock(return_value="conv_1"),
            ),
            patch(f"{MODULE}.add_workflow_execution_messages", AsyncMock()),
            patch(f"{MODULE}.reset_workflow_threads", AsyncMock()),
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

    for call in harness.increment.await_args_list:
        assert call.kwargs.get("is_successful") is not True
    captured = [call.args[1] for call in harness.capture_event.call_args_list if call.args]
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
