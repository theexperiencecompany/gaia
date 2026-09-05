"""Firing a briefing workflow runs the briefing pipeline, not a chat turn.

Three system workflows (daily brief, overnight work, weekly digest) share one
ARQ entry point with every other workflow, and the only thing separating them
is ``system_workflow_key``. Route one wrongly and the user gets somebody else's
brief — or an agent chat turn billed against their budget — so the key-to-
pipeline mapping is asserted per key, and the execution record the fire writes
is asserted whole: a briefing threads no conversation and records no tool calls.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    OVERNIGHT_WORK_WORKFLOW_KEY,
    WEEKLY_DIGEST_WORKFLOW_KEY,
)
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    Workflow,
    WorkflowStep,
)
from app.workers.tasks.workflow_tasks import _run_briefing_workflow, execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"
BRIEFING_SERVICE = "app.services.briefing.service"

#: What a briefing fire records: no conversation to thread, no tool calls to
#: replay, and the summary the execution history shows the user.
BRIEFING_SUMMARY = "Briefing delivered"


def _briefing_workflow(system_workflow_key: str) -> Workflow:
    return Workflow(
        id="wf_brief",
        user_id="u_1",
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
    )


class _Pipelines:
    """The three briefing entry points, each replaced by a stub."""

    def __init__(self) -> None:
        self.daily = AsyncMock()
        self.overnight = AsyncMock()
        self.weekly = AsyncMock()

    def patches(self) -> list:
        return [
            patch(f"{BRIEFING_SERVICE}.run_daily_briefing", self.daily),
            patch(f"{BRIEFING_SERVICE}.run_overnight_work", self.overnight),
            patch(f"{BRIEFING_SERVICE}.run_weekly_digest", self.weekly),
        ]


@pytest.fixture
def pipelines() -> _Pipelines:
    return _Pipelines()


@pytest.mark.unit
class TestKeyChoosesThePipeline:
    """``_run_briefing_workflow`` maps the key to exactly one pipeline."""

    async def test_daily_key_runs_the_daily_brief_for_that_user(
        self, pipelines: _Pipelines
    ) -> None:
        workflow = _briefing_workflow(DAILY_BRIEFING_WORKFLOW_KEY)

        with ExitStack() as stack:
            for patcher in pipelines.patches():
                stack.enter_context(patcher)
            summary = await _run_briefing_workflow(workflow)

        pipelines.daily.assert_awaited_once_with("u_1")
        pipelines.overnight.assert_not_awaited()
        pipelines.weekly.assert_not_awaited()
        assert summary == BRIEFING_SUMMARY

    async def test_overnight_key_runs_the_overnight_work_for_that_user(
        self, pipelines: _Pipelines
    ) -> None:
        workflow = _briefing_workflow(OVERNIGHT_WORK_WORKFLOW_KEY)

        with ExitStack() as stack:
            for patcher in pipelines.patches():
                stack.enter_context(patcher)
            summary = await _run_briefing_workflow(workflow)

        pipelines.overnight.assert_awaited_once_with("u_1")
        pipelines.daily.assert_not_awaited()
        pipelines.weekly.assert_not_awaited()
        assert summary == BRIEFING_SUMMARY

    async def test_weekly_key_runs_the_weekly_digest_for_that_user(
        self, pipelines: _Pipelines
    ) -> None:
        workflow = _briefing_workflow(WEEKLY_DIGEST_WORKFLOW_KEY)

        with ExitStack() as stack:
            for patcher in pipelines.patches():
                stack.enter_context(patcher)
            summary = await _run_briefing_workflow(workflow)

        pipelines.weekly.assert_awaited_once_with("u_1")
        pipelines.daily.assert_not_awaited()
        pipelines.overnight.assert_not_awaited()
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
            patch(f"{MODULE}.enforce_daily_cost_budget", AsyncMock()),
            patch(f"{MODULE}.create_execution", AsyncMock(return_value=self.execution)),
            patch(f"{MODULE}.complete_execution", self.complete_execution),
            patch(f"{MODULE}.WorkflowService", MagicMock(increment_execution_count=self.increment)),
            patch(f"{MODULE}.distrust_fresh_playbook", AsyncMock()),
            patch(f"{MODULE}.execute_workflow_as_chat", self.chat),
            patch(f"{MODULE}.capture_event", MagicMock()),
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

        pipelines.daily.assert_awaited_once_with("u_1")
        harness.chat.assert_not_awaited()

    async def test_the_execution_record_says_a_briefing_was_delivered(
        self, pipelines: _Pipelines
    ) -> None:
        """A briefing owns its own delivery, so it threads no conversation and
        replays no tool calls — the record has to say exactly that."""
        harness = _FireHarness(_briefing_workflow(WEEKLY_DIGEST_WORKFLOW_KEY))

        await _fire(harness, pipelines)

        assert harness.complete_execution.await_args.kwargs == {
            "execution_id": "exec_1",
            "status": "success",
            "summary": BRIEFING_SUMMARY,
            "conversation_id": None,
            "trace": [],
        }

    async def test_an_ordinary_workflow_still_runs_the_chat_turn(
        self, pipelines: _Pipelines
    ) -> None:
        """The branch is keyed off the system key alone, so a workflow without
        one must be untouched by it."""
        harness = _FireHarness(_briefing_workflow(system_workflow_key="todo_followup"))

        await _fire(harness, pipelines)

        harness.chat.assert_awaited_once()
        pipelines.daily.assert_not_awaited()
        pipelines.overnight.assert_not_awaited()
        pipelines.weekly.assert_not_awaited()
