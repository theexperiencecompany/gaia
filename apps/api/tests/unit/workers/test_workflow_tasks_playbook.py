"""Choosing between the playbook replay and the agent for one workflow fire.

The choice is the whole point: replay only while the frozen sequence still
matches the workflow the user has, and when a replay stops partway, finish the
run on the agent while telling it exactly what already happened. Getting the
fallback wrong sends the same email twice, so that hand-off is asserted on
content, not on "the agent was called".
"""

from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.agents import PLAYBOOK_FALLBACK_CONTEXT_KEY
from app.models.playbook_models import PlaybookDocument, PlaybookRunStatus, PlaybookStep
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    Workflow,
    WorkflowStep,
)
from app.services.workflow.playbook.runner import PlaybookRunResult
from app.services.workflow.playbook.workflow_hash import workflow_hash
from app.workers.tasks.workflow_tasks import execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"


@pytest.fixture(autouse=True)
def _onboarded_user():
    user = MagicMock()
    user.onboarding = {"completed": True}
    with patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=user)):
        yield


@pytest.fixture(autouse=True)
def _no_analytics():
    with patch(f"{MODULE}.capture_event"):
        yield


def _workflow() -> Workflow:
    return Workflow(
        id="wf_1",
        user_id="u_1",
        title="Daily agenda",
        description="Mail the agenda",
        prompt="Mail me today's agenda",
        steps=[
            WorkflowStep(id="s1", title="Read calendar", description="Read it", category="calendar")
        ],
        trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
    )


def _playbook(workflow: Workflow, *, stale: bool = False) -> PlaybookDocument:
    return PlaybookDocument(
        playbook_id="pb_1",
        workflow_id=workflow.id or "",
        user_id=workflow.user_id,
        workflow_hash=(
            "a-different-workflow" if stale else workflow_hash(workflow.prompt, workflow.steps)
        ),
        description="Mail the day's agenda",
        steps=[PlaybookStep(id="events", tool="list_events", args={})],
        synthesize="Say what happened.",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _Harness:
    """Every seam around the path choice, mocked. The choice itself is real."""

    def __init__(self, workflow: Workflow) -> None:
        self.workflow = workflow
        self.scheduler = AsyncMock()
        self.scheduler.get_task = AsyncMock(return_value=workflow)
        self.execution = MagicMock()
        self.execution.execution_id = "exec_1"
        self.complete_execution = AsyncMock()
        self.chat = AsyncMock(return_value=("conv_1", [RecordedCall(tool_name="agent_tool")]))
        self.playbook_run = AsyncMock()
        self.get_for_workflow = AsyncMock(return_value=None)
        self.record_run_outcome = AsyncMock()
        self.log = MagicMock()

    def playbook_event(self) -> dict[str, object]:
        """The ``playbook`` wide-event namespace this fire stamped.

        The namespace is the only way to tell from production why a run took the
        path it did, so it is asserted as a contract, not as incidental logging.
        """
        for call in self.log.set_ns.call_args_list:
            if call.args and call.args[0] == "playbook":
                return dict(call.kwargs)
        return {}

    def patches(self) -> list:
        return [
            patch(f"{MODULE}.workflow_scheduler", self.scheduler),
            patch(f"{MODULE}.create_execution", AsyncMock(return_value=self.execution)),
            patch(f"{MODULE}.complete_execution", self.complete_execution),
            patch(f"{MODULE}.WorkflowService", MagicMock(increment_execution_count=AsyncMock())),
            patch(f"{MODULE}.execute_workflow_as_chat", self.chat),
            patch(f"{MODULE}.execute_workflow_as_playbook", self.playbook_run),
            patch(
                f"{MODULE}.playbook_repository.get_for_workflow",
                self.get_for_workflow,
            ),
            patch(
                f"{MODULE}.playbook_repository.record_run_outcome",
                self.record_run_outcome,
            ),
            patch(f"{MODULE}.log", self.log),
        ]


async def _fire(harness: _Harness) -> str:
    """Fire the workflow with every seam in place and return the task's result."""
    with ExitStack() as stack:
        for patcher in harness.patches():
            stack.enter_context(patcher)
        return await execute_workflow_by_id({}, harness.workflow.id or "")


async def test_replay_runs_when_the_workflow_hash_matches() -> None:
    workflow = _workflow()
    harness = _Harness(workflow)
    playbook = _playbook(workflow)
    harness.get_for_workflow = AsyncMock(return_value=playbook)
    harness.playbook_run = AsyncMock(
        return_value=(
            "conv_1",
            PlaybookRunResult(
                ok=True,
                text="Agenda sent.",
                trace=[RecordedCall(tool_name="list_events")],
                llm_calls=1,
            ),
        )
    )

    await _fire(harness)

    harness.playbook_run.assert_awaited_once()
    harness.chat.assert_not_awaited()
    trace = harness.complete_execution.call_args.kwargs["trace"]
    assert [call.tool_name for call in trace] == ["list_events"]


async def test_the_agent_runs_when_the_workflow_hash_no_longer_matches() -> None:
    workflow = _workflow()
    harness = _Harness(workflow)
    harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow, stale=True))

    await _fire(harness)

    harness.playbook_run.assert_not_awaited()
    harness.chat.assert_awaited_once()
    harness.record_run_outcome.assert_not_awaited()


async def test_the_agent_runs_when_the_workflow_has_no_playbook() -> None:
    harness = _Harness(_workflow())

    await _fire(harness)

    harness.playbook_run.assert_not_awaited()
    harness.chat.assert_awaited_once()


async def test_a_playbook_lookup_failure_still_runs_the_workflow() -> None:
    """A playbooks-collection outage must cost the replay, never the user's run.

    Regression: the lookup was awaited unguarded, so any error reading the
    playbook propagated out of the fire and the workflow never ran at all. The
    playbook is an optimisation over the agentic path, not a precondition for
    it, so a failed read has to degrade to the agent.
    """
    harness = _Harness(_workflow())
    harness.get_for_workflow = AsyncMock(side_effect=RuntimeError("mongo down"))

    await _fire(harness)

    harness.playbook_run.assert_not_awaited()
    harness.chat.assert_awaited_once()


async def test_a_successful_replay_records_success() -> None:
    workflow = _workflow()
    harness = _Harness(workflow)
    harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
    harness.playbook_run = AsyncMock(
        return_value=("conv_1", PlaybookRunResult(ok=True, text="done", llm_calls=1))
    )

    await _fire(harness)

    harness.record_run_outcome.assert_awaited_once_with(
        workflow.id, workflow.user_id, PlaybookRunStatus.SUCCESS
    )


async def test_a_stopped_replay_records_failure_and_falls_back_to_the_agent() -> None:
    workflow = _workflow()
    harness = _Harness(workflow)
    harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
    harness.playbook_run = AsyncMock(
        return_value=(
            "conv_1",
            PlaybookRunResult(
                ok=False,
                failure="Playbook stopped at step 2 (send_email): rejected argument 'body'.",
                completed=["events (list_events) -> 12 events"],
                trace=[RecordedCall(tool_name="list_events")],
                llm_calls=0,
            ),
        )
    )

    await _fire(harness)

    harness.record_run_outcome.assert_awaited_once_with(
        workflow.id, workflow.user_id, PlaybookRunStatus.FAILED
    )
    harness.chat.assert_awaited_once()


async def test_the_fallback_run_is_told_what_already_happened() -> None:
    workflow = _workflow()
    harness = _Harness(workflow)
    harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
    harness.playbook_run = AsyncMock(
        return_value=(
            "conv_1",
            PlaybookRunResult(
                ok=False,
                failure="Playbook stopped at step 2 (send_email): rejected argument 'body'.",
                completed=["events (list_events) -> 12 events"],
                trace=[RecordedCall(tool_name="list_events")],
            ),
        )
    )

    await _fire(harness)

    context = harness.chat.call_args.args[2]
    note = context[PLAYBOOK_FALLBACK_CONTEXT_KEY]
    assert "events (list_events) -> 12 events" in note
    assert "send_email" in note
    assert "Do not repeat them" in note


async def test_the_fallback_keeps_the_replays_calls_on_the_execution_record() -> None:
    """The replay's side effects are history the next run has to be able to read."""
    workflow = _workflow()
    harness = _Harness(workflow)
    harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
    harness.playbook_run = AsyncMock(
        return_value=(
            "conv_1",
            PlaybookRunResult(
                ok=False,
                failure="Playbook stopped at step 2 (send_email): boom.",
                completed=["events (list_events) -> 12 events"],
                trace=[RecordedCall(tool_name="list_events")],
            ),
        )
    )

    await _fire(harness)

    trace = harness.complete_execution.call_args.kwargs["trace"]
    assert [call.tool_name for call in trace] == ["list_events", "agent_tool"]


@pytest.mark.asyncio
class TestPlaybookWideEvent:
    """What each path stamps on the run's wide event.

    ``mode``, ``reason`` and ``llm_calls`` are how anyone answers "why did this
    workflow not replay?" from production, and how the cost saving is measured
    at all. Wrong or missing values are invisible in review and in the UI, so
    they are pinned here rather than left as incidental logging.
    """

    async def test_a_workflow_with_no_playbook_says_so(self) -> None:
        harness = _Harness(_workflow())

        await _fire(harness)

        assert harness.playbook_event() == {
            "mode": "agent",
            "reason": "no_playbook",
            "llm_calls": 0,
        }

    async def test_an_edited_workflow_names_the_stale_hash(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow, stale=True)
        harness.get_for_workflow = AsyncMock(return_value=playbook)

        await _fire(harness)

        event = harness.playbook_event()
        assert event["mode"] == "agent"
        assert event["reason"] == "stale_workflow_hash"
        assert event["llm_calls"] == 0
        assert event["playbook_id"] == playbook.playbook_id

    async def test_a_failed_lookup_is_distinguishable_from_having_no_playbook(self) -> None:
        """Both fall back to the agent, so only the reason tells them apart."""
        harness = _Harness(_workflow())
        harness.get_for_workflow = AsyncMock(side_effect=RuntimeError("mongo down"))

        await _fire(harness)

        assert harness.playbook_event() == {
            "mode": "agent",
            "reason": "lookup_failed",
            "llm_calls": 0,
        }

    async def test_a_clean_replay_reports_the_model_calls_it_actually_spent(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(
            return_value=(
                "conv_1",
                PlaybookRunResult(
                    ok=True,
                    text="done",
                    trace=[RecordedCall(tool_name="list_todos")],
                    llm_calls=1,
                ),
            )
        )

        await _fire(harness)

        event = harness.playbook_event()
        assert event["mode"] == "replay"
        assert event["reason"] == "workflow_hash_match"
        assert event["llm_calls"] == 1
        assert event["playbook_id"] == playbook.playbook_id


@pytest.mark.unit
class TestWorkflowHash:
    """The fingerprint a stored playbook is validated against on every run.

    The digest is written into the playbook document and compared on every later
    run of that workflow. It therefore has to mean the same thing across
    processes, deploys and restarts: if the digest for an unchanged workflow
    ever moves, every playbook already stored stops matching and every workflow
    silently falls back to reasoning each run, which is exactly the cost this
    feature exists to avoid.
    """

    def _steps(self) -> list[WorkflowStep]:
        return [
            WorkflowStep(
                id="s1", title="Fetch mail", category="gmail", description="Read the inbox"
            )
        ]

    def test_the_digest_of_a_known_workflow_is_pinned(self) -> None:
        """A golden value, because the failure mode is invisible otherwise.

        Changing the serialisation (key order, separators, which fields go in)
        produces a perfectly good hash that simply is not the one in the
        database. If this assertion has to change, every stored playbook is
        being invalidated on purpose and the migration has to be deliberate.
        """
        assert (
            workflow_hash("Mail the agenda", self._steps())
            == "06df0ed3e452637317211d5ded39f8376f0e6a918cf8cd8ff26ecf37d95f7caf"
        )

    def test_the_same_workflow_hashes_the_same_every_time(self) -> None:
        assert workflow_hash("Mail the agenda", self._steps()) == workflow_hash(
            "Mail the agenda", self._steps()
        )

    def test_editing_the_prompt_changes_the_digest(self) -> None:
        """A rewritten prompt asks a different question, so the frozen sequence
        must stop being trusted."""
        assert workflow_hash("Mail the agenda", self._steps()) != workflow_hash(
            "Mail the agenda and the weather", self._steps()
        )

    def test_editing_a_step_changes_the_digest(self) -> None:
        """Every step field is part of what the playbook was written against."""
        base = self._steps()
        for field, value in (
            ("id", "s2"),
            ("title", "Fetch calendar"),
            ("category", "calendar"),
            ("description", "Read the calendar"),
        ):
            edited = [base[0].model_copy(update={field: value})]
            assert workflow_hash("Mail the agenda", base) != workflow_hash(
                "Mail the agenda", edited
            ), field

    def test_reordering_the_steps_changes_the_digest(self) -> None:
        """A playbook freezes an order, so a reordered workflow is a new one."""
        second = WorkflowStep(
            id="s2", title="Send mail", category="gmail", description="Send the digest"
        )
        forward = [*self._steps(), second]
        assert workflow_hash("Mail the agenda", forward) != workflow_hash(
            "Mail the agenda", list(reversed(forward))
        )
