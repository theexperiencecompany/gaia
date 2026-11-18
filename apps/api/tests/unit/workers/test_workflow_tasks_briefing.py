"""Firing a briefing workflow runs the briefing pipeline, not a chat turn.

Briefing workflows share one ARQ entry point with every other workflow, separated only
by the run their system_workflow_key declares, so the key-to-pipeline mapping is
asserted per key and the execution record is asserted whole.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.briefing import (
    BRIEFING_RUN_SUMMARIES,
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_WORKFLOW_KEY,
    BriefingKind,
    BriefingRunOutcome,
)
from app.constants.workflows import WorkflowDelivery
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    Workflow,
    WorkflowStep,
)
from app.services.briefing.errors import BriefingGenerationError
from app.services.system_workflows.runs import SYSTEM_RUNS
from app.workers.tasks.workflow_tasks import execute_workflow_by_id
from tests.helpers import captured_wide_event

MODULE = "app.workers.tasks.workflow_tasks"
RUNS = "app.services.system_workflows.definitions.briefing_runs"

#: What a briefing fire records: no conversation to thread, no tool calls to
#: replay, and the summary the execution history shows the user.
BRIEFING_SUMMARY = "Briefing delivered"


USER_ID = "64f1c0ffee0000000000abcd"


def _briefing_workflow(system_workflow_key: str) -> Workflow:
    return Workflow(
        id="wf_brief",
        user_id=USER_ID,
        title="Daily brief",
        description="The morning brief",
        prompt="Brief me",
        steps=[
            WorkflowStep(
                id="s1",
                title="Curate",
                description="Curate the brief",
                category="general",
            )
        ],
        trigger_config=TriggerConfig(type=TriggerType.SCHEDULE, enabled=True),
        system_workflow_key=system_workflow_key,
        delivery=WorkflowDelivery.SILENT,
    )


class _Pipelines:
    """The one briefing entry point, replaced by a stub."""

    def __init__(self) -> None:
        self.run = AsyncMock(return_value=BriefingRunOutcome.SENT)
        self.release = AsyncMock()

    def patches(self) -> list:
        return [
            patch(f"{RUNS}.run_brief", self.run),
            patch(f"{RUNS}.release_after_daily_run", self.release),
        ]


@pytest.fixture
def pipelines() -> _Pipelines:
    return _Pipelines()


@pytest.mark.unit
class TestKeyChoosesThePipeline:
    """Each briefing key's declared run is exactly one pipeline."""

    async def test_daily_key_runs_the_daily_brief_for_that_user(
        self, pipelines: _Pipelines
    ) -> None:
        workflow = _briefing_workflow(DAILY_BRIEFING_WORKFLOW_KEY)

        with ExitStack() as stack:
            for patcher in pipelines.patches():
                stack.enter_context(patcher)
            async with captured_wide_event() as event:
                summary = await SYSTEM_RUNS[DAILY_BRIEFING_WORKFLOW_KEY](workflow)

        pipelines.run.assert_awaited_once_with(USER_ID, BriefingKind.DAILY)
        assert summary == BRIEFING_SUMMARY
        assert event["workflow"] == {"briefing_outcome": "sent"}

    @pytest.mark.regression
    async def test_a_daily_run_hands_its_outcome_to_the_held_release(
        self, pipelines: _Pipelines
    ) -> None:
        pipelines.run.return_value = BriefingRunOutcome.WINBACK_BACKOFF

        with ExitStack() as stack:
            for patcher in pipelines.patches():
                stack.enter_context(patcher)
            await SYSTEM_RUNS[DAILY_BRIEFING_WORKFLOW_KEY](
                _briefing_workflow(DAILY_BRIEFING_WORKFLOW_KEY)
            )

        pipelines.release.assert_awaited_once_with(USER_ID, BriefingRunOutcome.WINBACK_BACKOFF)

    async def test_weekly_key_runs_the_weekly_digest_for_that_user(
        self, pipelines: _Pipelines
    ) -> None:
        workflow = _briefing_workflow(WEEKLY_DIGEST_WORKFLOW_KEY)

        with ExitStack() as stack:
            for patcher in pipelines.patches():
                stack.enter_context(patcher)
            summary = await SYSTEM_RUNS[WEEKLY_DIGEST_WORKFLOW_KEY](workflow)

        pipelines.run.assert_awaited_once_with(USER_ID, BriefingKind.WEEKLY)
        pipelines.release.assert_not_awaited()
        assert summary == BRIEFING_SUMMARY


class _FireHarness:
    """Every seam a fire touches around the run itself, mocked."""

    def __init__(self, workflow: Workflow) -> None:
        self.workflow = workflow
        self.scheduler = AsyncMock()
        self.scheduler.get_task = AsyncMock(return_value=workflow)
        self.execution = MagicMock()
        self.execution.execution_id = "exec_1"
        self.complete_execution = AsyncMock()
        self.chat = AsyncMock(return_value=("conv_1", []))
        self.increment = AsyncMock()

    def patches(self) -> list:
        return [
            patch(f"{MODULE}.workflow_scheduler", self.scheduler),
            patch(f"{MODULE}.enforce_cost_budget", AsyncMock()),
            patch(f"{MODULE}.create_execution", AsyncMock(return_value=self.execution)),
            patch(f"{MODULE}.complete_execution", self.complete_execution),
            patch(f"{MODULE}.WorkflowService", MagicMock(increment_execution_count=self.increment)),
            patch(f"{MODULE}.distrust_fresh_playbook", AsyncMock()),
            patch(f"{MODULE}.execute_workflow_as_chat", self.chat),
            patch(f"{MODULE}.capture", MagicMock()),
            patch(f"{MODULE}._completed_onboarding", AsyncMock(return_value=True)),
            patch(f"{MODULE}._claim_scheduled_fire", AsyncMock(return_value=True)),
        ]


async def _fire(harness: _FireHarness, pipelines: _Pipelines) -> str:
    """Fire the workflow through the real ARQ entry point."""
    with ExitStack() as stack:
        for patcher in harness.patches() + pipelines.patches():
            stack.enter_context(patcher)
        return await execute_workflow_by_id(
            {}, harness.workflow.id or "", {"trigger_type": TriggerType.SCHEDULE.value}
        )


@pytest.mark.unit
class TestTheFireTakesTheBriefingPath:
    async def test_a_briefing_fire_never_runs_a_chat_turn(self, pipelines: _Pipelines) -> None:
        harness = _FireHarness(_briefing_workflow(DAILY_BRIEFING_WORKFLOW_KEY))

        await _fire(harness, pipelines)

        pipelines.run.assert_awaited_once_with(USER_ID, BriefingKind.DAILY)
        harness.chat.assert_not_awaited()

    async def test_the_execution_record_says_a_briefing_was_delivered(
        self, pipelines: _Pipelines
    ) -> None:
        """The record says a briefing owns its delivery: no conversation, no tool calls."""
        harness = _FireHarness(_briefing_workflow(WEEKLY_DIGEST_WORKFLOW_KEY))

        await _fire(harness, pipelines)

        assert harness.complete_execution.await_args.kwargs == {
            "execution_id": "exec_1",
            "status": "success",
            "summary": BRIEFING_SUMMARY,
            "conversation_id": None,
            "trace": [],
        }

    async def test_a_skipped_briefing_says_why_instead_of_claiming_delivery(
        self, pipelines: _Pipelines
    ) -> None:
        pipelines.run.return_value = BriefingRunOutcome.DORMANT
        harness = _FireHarness(_briefing_workflow(DAILY_BRIEFING_WORKFLOW_KEY))

        await _fire(harness, pipelines)

        summary = harness.complete_execution.await_args.kwargs["summary"]
        assert summary == BRIEFING_RUN_SUMMARIES[BriefingRunOutcome.DORMANT]
        assert summary != BRIEFING_SUMMARY

    async def test_an_ordinary_workflow_still_runs_the_chat_turn(
        self, pipelines: _Pipelines
    ) -> None:
        """A workflow without a system key still runs the ordinary chat turn."""
        harness = _FireHarness(_briefing_workflow(system_workflow_key="todo_followup"))

        await _fire(harness, pipelines)

        harness.chat.assert_awaited_once()
        pipelines.run.assert_not_awaited()


@pytest.mark.unit
class TestAFailedBrief:
    """A failed brief told the user "Workflow Failed: Daily brief" for a workflow they never see."""

    async def _fail(
        self, workflow: Workflow, pipelines: _Pipelines
    ) -> tuple[_FireHarness, AsyncMock]:
        pipelines.run.side_effect = BriefingGenerationError("the prose contradicts its items")
        harness = _FireHarness(workflow)
        harness.chat.side_effect = RuntimeError("the chat turn broke")
        notify = AsyncMock()
        with patch(f"{MODULE}.notification_service.create_notification", notify):
            await _fire(harness, pipelines)
        return harness, notify

    async def test_it_is_recorded_failed_and_never_notified_as_a_workflow(
        self, pipelines: _Pipelines
    ) -> None:
        harness, notify = await self._fail(
            _briefing_workflow(DAILY_BRIEFING_WORKFLOW_KEY), pipelines
        )

        notify.assert_not_awaited()
        assert harness.complete_execution.await_args.kwargs["status"] == "failed"
        assert harness.complete_execution.await_args.kwargs["error_message"] == (
            "the prose contradicts its items"
        )

    async def test_a_users_own_workflow_that_fails_still_tells_them(
        self, pipelines: _Pipelines
    ) -> None:
        _harness, notify = await self._fail(_briefing_workflow("todo_followup"), pipelines)

        [call] = notify.await_args_list
        assert call.args[0].content.title == "Workflow Failed: Daily brief"
