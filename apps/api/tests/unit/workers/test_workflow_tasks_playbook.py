"""Choosing between the playbook replay and the agent for one workflow fire.

The choice is the whole point: replay only while the frozen sequence still
matches the workflow the user has, and when a replay stops partway, finish the
run on the agent while telling it exactly what already happened. Getting the
fallback wrong sends the same email twice, so that hand-off is asserted on
content, not on "the agent was called".
"""

import asyncio
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID

import pytest

from app.agents.prompts.playbook_prompts import (
    PLAYBOOK_FALLBACK_TEMPLATE,
    PLAYBOOK_SUSPECT_FALLBACK_TEMPLATE,
)
from app.constants.agents import (
    PLAYBOOK_FALLBACK_CONTEXT_KEY,
    PLAYBOOK_HEAL_ATTEMPT_LIMIT,
    PLAYBOOK_SUSPECT_STREAK_LIMIT,
    AgentTag,
    wrap_agent_payload,
)
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.log_tags import LogTag
from app.models.playbook_models import (
    PlaybookDocument,
    PlaybookRunOutcome,
    PlaybookRunStatus,
    PlaybookStep,
)
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import (
    PlaybookDiscard,
    TriggerConfig,
    TriggerType,
    Workflow,
    WorkflowStep,
)
from app.services.workflow.execution_service import WorkflowFireQueued
from app.services.workflow.playbook.check import HEAL_STATUSES
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.runner import FALLBACK_LINE_MAX_CHARS, PlaybookRunResult
from app.services.workflow.playbook.workflow_hash import workflow_hash
from app.utils.timezone import Timezone
from app.workers.tasks.workflow_tasks import (
    AGENT_RUN_SUMMARY,
    HEAL_RUN_SUMMARY,
    OVERLAPPED_SUMMARY,
    REPLAY_FLAGGED_SUMMARY,
    REPLAY_NARRATION_FAILED_SUMMARY,
    REPLAY_STOPPED_SUMMARY,
    REPLAY_SUMMARY,
    SHORTCUT_DISCARDED_SUMMARY,
    _fallback_note,
    _notify_replay_finished,
    _resolve_workflow_user,
    execute_workflow_by_id,
)

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
            WorkflowStep(
                id="s1",
                title="Read calendar",
                description="Read it",
                category="calendar",
            )
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
        result_brief="Say what happened.",
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
        self.record_run_outcome = AsyncMock(return_value=None)
        self.increment_heal_attempts = AsyncMock(return_value=None)
        self.delete_for_workflow = AsyncMock(return_value=True)
        self.update_workflow = AsyncMock(return_value=None)
        self.add_messages = AsyncMock()
        self.platform_delivery = AsyncMock()
        self.completion_notification = AsyncMock()
        self.tiered_limit = AsyncMock()
        self.log = MagicMock()
        #: Seams a single test needs on top of the shared set, entered last so
        #: they win over anything the harness already patched.
        self.extra: list = []

    def playbook_event(self) -> dict[str, object]:
        """The ``playbook`` wide-event namespace this fire stamped.

        The namespace is the only way to tell from production why a run took the
        path it did, so it is asserted as a contract, not as incidental logging.
        """
        for entry in self.log.set_ns.call_args_list:
            if entry.args and entry.args[0] == "playbook":
                return dict(entry.kwargs)
        return {}

    def patches(self) -> list:
        return [
            patch(f"{MODULE}.workflow_scheduler", self.scheduler),
            patch(f"{MODULE}.create_execution", AsyncMock(return_value=self.execution)),
            patch(f"{MODULE}.complete_execution", self.complete_execution),
            patch(
                f"{MODULE}.WorkflowService",
                MagicMock(increment_execution_count=AsyncMock()),
            ),
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
            patch(
                f"{MODULE}.playbook_repository.delete_for_workflow",
                self.delete_for_workflow,
            ),
            patch(
                f"{MODULE}.playbook_repository.increment_heal_attempts",
                self.increment_heal_attempts,
            ),
            patch(
                f"{MODULE}.workflow_repository.update_for_user",
                self.update_workflow,
            ),
            patch(f"{MODULE}.add_playbook_run_messages", self.add_messages),
            patch(f"{MODULE}.deliver_result_to_platforms", self.platform_delivery),
            patch(
                f"{MODULE}.send_workflow_completion_notification",
                self.completion_notification,
            ),
            patch(f"{MODULE}.enforce_tiered_limit", self.tiered_limit),
            patch(f"{MODULE}.log", self.log),
        ] + self.extra

    def summary(self) -> str:
        """What the execution record says this fire did."""
        return str(self.complete_execution.await_args.kwargs["summary"])

    def discard_record(self) -> PlaybookDiscard:
        """What this fire wrote onto the workflow about the shortcut it dropped."""
        self.update_workflow.assert_awaited_once()
        update = self.update_workflow.await_args.args[2]
        assert update.last_playbook_discard is not None
        return update.last_playbook_discard

    def delivered_text(self) -> str:
        """What the user reads in the conversation for this fire's replay."""
        self.add_messages.assert_awaited_once()
        return str(self.add_messages.await_args.kwargs["response"])


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


@pytest.mark.parametrize("status", [PlaybookRunStatus.SUSPECT, PlaybookRunStatus.FAILED])
async def test_a_distrusted_playbook_sends_the_fire_to_the_agent_to_heal(
    status: PlaybookRunStatus,
) -> None:
    """Seen live: a suspect playbook was replayed again on the next fire, went
    suspect again, and was deleted by the streak limit before the heal brief
    ever reached an agent. A playbook the last run did not trust is not
    replayed; the fire runs agentically, and the check brief carries the reason."""
    workflow = _workflow()
    harness = _Harness(workflow)
    harness.get_for_workflow = AsyncMock(
        return_value=_playbook(workflow).model_copy(
            update={
                "last_run_status": status,
                "last_run_reason": "fetch returned nothing",
            }
        )
    )

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
        workflow.id,
        workflow.user_id,
        PlaybookRunOutcome(PlaybookRunStatus.SUCCESS, reason=None, counts_toward_streak=True),
        playbook_id="pb_1",
        revision=0,
    )
    assert harness.delivered_text() == "done", "a trusted result is delivered as it is"
    harness.delete_for_workflow.assert_not_awaited()


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
        workflow.id,
        workflow.user_id,
        PlaybookRunOutcome(
            PlaybookRunStatus.FAILED,
            reason="Playbook stopped at step 2 (send_email): rejected argument 'body'.",
            counts_toward_streak=True,
        ),
        playbook_id="pb_1",
        revision=0,
    )
    harness.chat.assert_awaited_once()
    # A stopped replay leaves the turn to the agent run that takes over.
    harness.add_messages.assert_not_awaited()


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


def _stopped_replay() -> tuple[str, PlaybookRunResult]:
    return (
        "conv_1",
        PlaybookRunResult(
            ok=False,
            failure="Playbook stopped at step 2 (send_email): boom.",
            completed=["events (list_events) -> 12 events"],
            trace=[RecordedCall(tool_name="list_events")],
        ),
    )


async def test_a_fallback_that_raises_still_records_the_replays_calls() -> None:
    """The replay's calls happened whether or not the agent got to finish.

    A raise out of the fallback used to reach the generic failure path with no
    trace at all, so the record said this fire did nothing and the next fire
    replayed from step one — repeating every side effect the first one caused.
    """
    workflow = _workflow()
    harness = _Harness(workflow)
    harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
    harness.playbook_run = AsyncMock(return_value=_stopped_replay())
    harness.chat = AsyncMock(side_effect=RuntimeError("agent exploded"))

    with patch(f"{MODULE}.notification_service.create_notification", AsyncMock()):
        await _fire(harness)

    harness.complete_execution.assert_awaited_once()
    kwargs = harness.complete_execution.await_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["error_message"] == "agent exploded"
    assert kwargs["conversation_id"] == "conv_1"
    assert [call.tool_name for call in kwargs["trace"]] == ["list_events"]


async def test_a_failed_outcome_write_after_a_replay_still_records_its_calls() -> None:
    """Same rule one step earlier: the playbook bookkeeping failing must not
    erase what the replay already did."""
    workflow = _workflow()
    harness = _Harness(workflow)
    harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
    harness.playbook_run = AsyncMock(return_value=_stopped_replay())
    harness.record_run_outcome = AsyncMock(side_effect=ConnectionError("mongo away"))

    with patch(f"{MODULE}.notification_service.create_notification", AsyncMock()):
        await _fire(harness)

    kwargs = harness.complete_execution.await_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["error_message"] == "mongo away"
    assert [call.tool_name for call in kwargs["trace"]] == ["list_events"]
    harness.chat.assert_not_awaited()


def _suspect_replay(
    reason: str, *, source: Literal["record", "narration"] = "record"
) -> tuple[str, PlaybookRunResult]:
    return (
        "conv_1",
        PlaybookRunResult(
            ok=True,
            text="Nothing on the calendar today.",
            suspect=reason,
            suspect_source=source,
            trace=[RecordedCall(tool_name="list_events")],
            llm_calls=1,
        ),
    )


def _recorded(playbook: PlaybookDocument, streak: int) -> PlaybookDocument:
    """The document ``record_run_outcome`` hands back after a suspect run."""
    return playbook.model_copy(
        update={"last_run_status": PlaybookRunStatus.SUSPECT, "suspect_streak": streak}
    )


@pytest.mark.asyncio
class TestSuspectReplay:
    """A replay that finished but whose result is not trusted.

    It is not delivered. Nothing stopped, so the agent must not rerun the side
    effects blind, but a confident wrong brief must never reach the user
    either: the fire is finished by the agent, told what already ran and why
    the result was not trusted, exactly like a replay that stopped partway.
    A playbook that keeps producing suspect results has to go.
    """

    REASON = "step events (list_events) returned no items"

    @pytest.mark.parametrize("source", ["record", "narration"])
    async def test_records_suspect_with_the_reason_whatever_flagged_it(
        self, source: Literal["record", "narration"]
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay(self.REASON, source=source))
        harness.record_run_outcome = AsyncMock(return_value=_recorded(playbook, 1))

        await _fire(harness)

        harness.record_run_outcome.assert_awaited_once_with(
            workflow.id,
            workflow.user_id,
            PlaybookRunOutcome(
                PlaybookRunStatus.SUSPECT,
                reason=self.REASON,
                counts_toward_streak=source == "record",
            ),
            playbook_id="pb_1",
            revision=0,
        )

    async def test_the_agent_finishes_the_fire_told_why_and_what_already_ran(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        conversation_id, result = _suspect_replay(self.REASON)
        harness.playbook_run = AsyncMock(
            return_value=(
                conversation_id,
                result.model_copy(update={"completed": ["events (list_events) -> 0 events"]}),
            )
        )
        harness.record_run_outcome = AsyncMock(return_value=_recorded(playbook, 1))

        await _fire(harness)

        harness.chat.assert_awaited_once()
        note = harness.chat.call_args.args[2][PLAYBOOK_FALLBACK_CONTEXT_KEY]
        assert self.REASON in note
        assert "events (list_events) -> 0 events" in note
        assert "Do not repeat them" in note
        assert "rewriting the playbook or disabling it" in note

    async def test_the_untrusted_result_is_neither_written_nor_notified(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay(self.REASON))
        harness.record_run_outcome = AsyncMock(return_value=_recorded(playbook, 1))

        await _fire(harness)

        harness.add_messages.assert_not_awaited()
        harness.platform_delivery.assert_not_awaited()
        harness.completion_notification.assert_not_awaited()

    async def test_the_record_keeps_the_replays_calls_ahead_of_the_agents(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay(self.REASON))
        harness.record_run_outcome = AsyncMock(return_value=_recorded(playbook, 1))
        harness.chat = AsyncMock(return_value=("conv_1", [RecordedCall(tool_name="send_email")]))

        await _fire(harness)

        kwargs = harness.complete_execution.await_args.kwargs
        assert kwargs["status"] == "success"
        assert [call.tool_name for call in kwargs["trace"]] == [
            "list_events",
            "send_email",
        ]
        assert kwargs["summary"] == REPLAY_FLAGGED_SUMMARY.format(reason=self.REASON)

    async def test_a_streak_at_the_limit_deletes_the_playbook_before_the_agent_runs(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay(self.REASON))
        harness.record_run_outcome = AsyncMock(
            return_value=_recorded(playbook, PLAYBOOK_SUSPECT_STREAK_LIMIT)
        )

        await _fire(harness)

        harness.delete_for_workflow.assert_awaited_once_with(workflow.id, workflow.user_id)
        harness.chat.assert_awaited_once()
        warnings = [
            call
            for call in harness.log.warning.call_args_list
            if call.kwargs.get("reason") == "suspect_streak_exhausted"
        ]
        assert len(warnings) == 1
        kwargs = warnings[0].kwargs
        assert kwargs["workflow_id"] == workflow.id
        assert kwargs["playbook_id"] == playbook.playbook_id
        assert kwargs["suspect_reason"] == self.REASON

    async def test_a_streak_below_the_limit_keeps_the_playbook(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay(self.REASON))
        harness.record_run_outcome = AsyncMock(
            return_value=_recorded(playbook, PLAYBOOK_SUSPECT_STREAK_LIMIT - 1)
        )

        await _fire(harness)

        harness.delete_for_workflow.assert_not_awaited()
        harness.chat.assert_awaited_once()

    async def test_the_wide_event_names_the_outcome_and_reason(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay(self.REASON))
        harness.record_run_outcome = AsyncMock(
            return_value=_recorded(playbook, PLAYBOOK_SUSPECT_STREAK_LIMIT)
        )

        await _fire(harness)

        event = harness.playbook_event()
        assert event["mode"] == "agent"
        assert event["reason"] == "replay_suspect"
        assert event["outcome"] == "suspect"
        assert event["suspect_reason"] == self.REASON
        assert event["disabled"] is True
        assert event["llm_calls"] == 1

    async def test_a_trusted_replay_reports_a_success_outcome(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(
            return_value=(
                "conv_1",
                PlaybookRunResult(ok=True, text="done", llm_calls=1),
            )
        )

        await _fire(harness)

        event = harness.playbook_event()
        assert event["mode"] == "replay"
        assert event["outcome"] == "success"
        harness.chat.assert_not_awaited()


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

    async def test_a_failed_lookup_is_distinguishable_from_having_no_playbook(
        self,
    ) -> None:
        """Both fall back to the agent, so only the reason tells them apart."""
        harness = _Harness(_workflow())
        harness.get_for_workflow = AsyncMock(side_effect=RuntimeError("mongo down"))

        await _fire(harness)

        assert harness.playbook_event() == {
            "mode": "agent",
            "reason": "lookup_failed",
            "llm_calls": 0,
        }

    async def test_a_clean_replay_reports_the_model_calls_it_actually_spent(
        self,
    ) -> None:
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
                id="s1",
                title="Fetch mail",
                category="gmail",
                description="Read the inbox",
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


@pytest.mark.asyncio
class TestStoppedReplayWideEvent:
    """What a partly-run replay leaves behind for the next run and for support.

    A replay that stops is the one case where BOTH paths ran, so the record has
    to say the replay was tried, name the playbook, and keep the replay's own
    calls ahead of the agent's. Losing any of that either hides that a playbook
    is drifting or lets the next run repeat a side effect.
    """

    @staticmethod
    def _stopped(workflow):
        return AsyncMock(
            return_value=(
                "conv_1",
                PlaybookRunResult(
                    ok=False,
                    text="",
                    trace=[RecordedCall(tool_name="list_todos")],
                    llm_calls=1,
                    failure="Playbook stopped at step 2 (send_email): rejected argument 'body'.",
                ),
            )
        )

    async def test_a_stopped_replay_is_reported_as_a_replay_that_stopped(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = self._stopped(workflow)

        await _fire(harness)

        event = harness.playbook_event()
        assert event["mode"] == "agent", "the agent finished the run"
        assert event["reason"] == "replay_stopped", (
            "must be distinguishable from a workflow that never had a playbook"
        )
        assert event["playbook_id"] == playbook.playbook_id
        assert event["llm_calls"] == 1, "the replay's own model call still cost the user"

    async def test_the_stop_is_logged_with_the_failure_that_caused_it(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = self._stopped(workflow)

        await _fire(harness)

        warnings = [
            call
            for call in harness.log.warning.call_args_list
            if "replay stopped" in str(call.args[0]).lower()
        ]
        assert len(warnings) == 1
        kwargs = warnings[0].kwargs
        assert kwargs["workflow_id"] == workflow.id
        assert kwargs["playbook_id"] == playbook.playbook_id
        assert "send_email" in kwargs["failure"], (
            "without the failure text nobody can tell why the playbook drifted"
        )

    async def test_the_replays_calls_come_before_the_agents_on_the_record(self) -> None:
        """Order is the record of what already happened, in the order it happened.

        The next run reads this trace as its history and the fallback agent is
        told not to repeat the replay's calls. Dropping them, or putting the
        agent's first, tells the next run a side effect never occurred.
        """
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = self._stopped(workflow)
        harness.chat = AsyncMock(return_value=("conv_1", [RecordedCall(tool_name="send_email")]))

        await _fire(harness)

        trace = harness.complete_execution.await_args.kwargs["trace"]

        assert [call.tool_name for call in trace] == ["list_todos", "send_email"]


def _finished_replay(text: str = "Agenda sent.") -> tuple[str, PlaybookRunResult]:
    return (
        "conv_1",
        PlaybookRunResult(
            ok=True,
            text=text,
            trace=[RecordedCall(tool_name="list_events")],
            llm_calls=1,
        ),
    )


@pytest.mark.asyncio
class TestReplayCompletionNotification:
    """A finished replay is delivered the way an agent run is delivered.

    The executor path pushes the result into the user's linked platforms and
    then sends the in-app heads-up, gated on ``notify_on_completion``. A replay
    used to write the conversation turn and stop, so a user who asked to be
    notified stopped hearing from the workflow the moment a playbook was
    written, and the review label never reached them.
    """

    async def test_a_finished_replay_notifies_with_the_delivered_text(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_finished_replay())

        await _fire(harness)

        harness.platform_delivery.assert_awaited_once()
        assert harness.platform_delivery.await_args.kwargs["notification_text"] == "Agenda sent."
        assert harness.platform_delivery.await_args.kwargs["user_id"] == workflow.user_id
        harness.completion_notification.assert_awaited_once_with(
            workflow_id=workflow.id,
            workflow_title=workflow.title,
            conversation_id="conv_1",
            user_id=workflow.user_id,
        )

    async def test_an_untrusted_replay_leaves_the_notification_to_the_agent(
        self,
    ) -> None:
        """The agent finishes the fire and its own delivery path notifies once."""
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay("list_events was empty"))
        harness.record_run_outcome = AsyncMock(return_value=_recorded(playbook, 1))

        await _fire(harness)

        harness.chat.assert_awaited_once()
        harness.platform_delivery.assert_not_awaited()
        harness.completion_notification.assert_not_awaited()

    async def test_a_silent_workflow_is_not_notified(self) -> None:
        workflow = _workflow().model_copy(update={"notify_on_completion": False})
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_finished_replay())

        await _fire(harness)

        harness.add_messages.assert_awaited_once()
        harness.platform_delivery.assert_not_awaited()
        harness.completion_notification.assert_not_awaited()

    async def test_a_stopped_replay_leaves_the_notification_to_the_agent(self) -> None:
        """The fallback agent run delivers its own result through the executor path."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_stopped_replay())

        await _fire(harness)

        harness.chat.assert_awaited_once()
        harness.platform_delivery.assert_not_awaited()
        harness.completion_notification.assert_not_awaited()

    async def test_a_notification_failure_does_not_fail_the_run(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_finished_replay())
        harness.platform_delivery = AsyncMock(side_effect=RuntimeError("telegram down"))

        result = await _fire(harness)

        assert "executed successfully" in result
        assert harness.complete_execution.await_args.kwargs["status"] == "success"


@pytest.mark.asyncio
class TestStalePlaybookIsDiscarded:
    """A playbook whose hash no longer matches is deleted, not merely skipped.

    The check brief asks for a playbook only when the workflow has none, so a
    stale one left on file was never re-authored: the workflow ran at full
    agent cost on every fire, forever, with the stale document sitting there.
    """

    async def test_the_stale_playbook_is_deleted_before_the_agent_runs(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow, stale=True)
        harness.get_for_workflow = AsyncMock(return_value=playbook)

        await _fire(harness)

        harness.delete_for_workflow.assert_awaited_once_with(workflow.id, workflow.user_id)
        harness.chat.assert_awaited_once()
        harness.playbook_run.assert_not_awaited()
        warnings = [
            call.kwargs
            for call in harness.log.warning.call_args_list
            if call.kwargs.get("reason") == "stale_workflow_hash"
        ]
        assert len(warnings) == 1
        assert warnings[0]["playbook_id"] == playbook.playbook_id

    async def test_a_failed_delete_still_runs_the_workflow(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow, stale=True))
        harness.delete_for_workflow = AsyncMock(side_effect=RuntimeError("mongo away"))

        result = await _fire(harness)

        assert "executed successfully" in result
        harness.chat.assert_awaited_once()


def _distrusted(workflow: Workflow, attempts: int = 0) -> PlaybookDocument:
    return _playbook(workflow).model_copy(
        update={
            "last_run_status": PlaybookRunStatus.SUSPECT,
            "last_run_reason": "fetch returned nothing",
            "heal_attempts": attempts,
        }
    )


@pytest.mark.asyncio
class TestHealAttemptsAreBounded:
    """A heal run that lapses, declines, or has its rewrite refused leaves the
    playbook FAILED/SUSPECT, so without a bound every later fire ran the agent
    with the heal brief forever and the streak limit never fired (no replay
    ever happened again)."""

    async def test_a_heal_run_is_counted_only_after_the_agent_completes(self) -> None:
        """Seen live: a DNS outage failed two fires in under a second, before any
        agent ran, and each spent a heal attempt. An attempt is a heal run that
        completed and still left the playbook distrusted; a fire that never
        reached the agent is not one."""
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _distrusted(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        order: list[str] = []
        harness.chat = AsyncMock(
            side_effect=lambda *a, **k: (order.append("agent"), ("conv_1", []))[1]
        )
        harness.increment_heal_attempts = AsyncMock(
            side_effect=lambda *a, **k: (
                order.append("count"),
                _distrusted(workflow, 1),
            )[1]
        )

        await _fire(harness)

        assert order == ["agent", "count"]
        harness.increment_heal_attempts.assert_awaited_once_with(
            workflow.id,
            workflow.user_id,
            playbook_id=playbook.playbook_id,
            revision=playbook.revision,
        )
        harness.delete_for_workflow.assert_not_awaited()
        event = harness.playbook_event()
        assert event["reason"] == "heal"
        assert event["heal_attempts"] == 0

    async def test_a_heal_run_that_never_reaches_the_agent_is_not_counted(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_distrusted(workflow))
        harness.chat = AsyncMock(side_effect=OSError("nodename nor servname provided"))

        await _fire(harness)

        harness.increment_heal_attempts.assert_not_awaited()

    async def test_the_last_allowed_attempt_still_heals(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(
            return_value=_distrusted(workflow, PLAYBOOK_HEAL_ATTEMPT_LIMIT - 1)
        )

        await _fire(harness)

        harness.delete_for_workflow.assert_not_awaited()
        harness.chat.assert_awaited_once()
        assert harness.playbook_event()["reason"] == "heal"

    async def test_past_the_limit_the_playbook_is_deleted_and_the_agent_runs(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _distrusted(workflow, PLAYBOOK_HEAL_ATTEMPT_LIMIT)
        harness.get_for_workflow = AsyncMock(return_value=playbook)

        await _fire(harness)

        harness.increment_heal_attempts.assert_not_awaited()

        harness.delete_for_workflow.assert_awaited_once_with(workflow.id, workflow.user_id)
        harness.chat.assert_awaited_once()
        harness.playbook_run.assert_not_awaited()
        event = harness.playbook_event()
        assert event["mode"] == "agent"
        assert event["reason"] == "heal_attempts_exhausted"
        assert event["heal_attempts"] == PLAYBOOK_HEAL_ATTEMPT_LIMIT
        warnings = [
            call.kwargs
            for call in harness.log.warning.call_args_list
            if call.kwargs.get("reason") == "heal_attempts_exhausted"
        ]
        assert len(warnings) == 1
        assert warnings[0]["playbook_id"] == playbook.playbook_id
        assert warnings[0]["heal_attempts"] == PLAYBOOK_HEAL_ATTEMPT_LIMIT

    async def test_a_playbook_replaced_between_read_and_count_still_heals(self) -> None:
        """The count landing on nothing means the playbook changed under us; the
        fire still runs, on the agent, and nothing is deleted on a guess."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_distrusted(workflow))
        harness.increment_heal_attempts = AsyncMock(return_value=None)

        await _fire(harness)

        harness.chat.assert_awaited_once()
        harness.delete_for_workflow.assert_not_awaited()


@pytest.mark.asyncio
class TestExecutionRecordSummary:
    """The execution record says how the fire completed, not just that it did.

    Every replay used to be recorded as ``summary="Workflow executed"``, so a
    flagged replay was indistinguishable from a clean agent run in the history.
    """

    async def test_a_clean_replay_says_how_many_steps_it_replayed(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_finished_replay())

        await _fire(harness)

        assert harness.complete_execution.await_args.kwargs["status"] == "success"
        assert harness.summary() == REPLAY_SUMMARY

    async def test_a_flagged_replay_says_so_with_the_reason(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay("list_events was empty."))
        harness.record_run_outcome = AsyncMock(return_value=_recorded(playbook, 1))

        await _fire(harness)

        assert harness.complete_execution.await_args.kwargs["status"] == "success"
        assert harness.summary() == REPLAY_FLAGGED_SUMMARY.format(reason="list_events was empty")

    async def test_a_stopped_replay_says_the_agent_finished(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_stopped_replay())

        await _fire(harness)

        assert harness.summary() == REPLAY_STOPPED_SUMMARY

    async def test_an_agent_run_keeps_the_plain_summary(self) -> None:
        harness = _Harness(_workflow())

        await _fire(harness)

        assert harness.summary() == AGENT_RUN_SUMMARY


@pytest.mark.asyncio
class TestOutcomeIsScopedToTheReplayedRevision:
    """``playbook_id`` survives a rewrite, so the id alone never guarded anything."""

    async def test_the_outcome_carries_the_revision_the_worker_read(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(
            return_value=_playbook(workflow).model_copy(update={"revision": 4})
        )
        harness.playbook_run = AsyncMock(return_value=_finished_replay())

        await _fire(harness)

        assert harness.record_run_outcome.await_args.kwargs["revision"] == 4

    async def test_an_outcome_that_did_not_land_skips_the_streak_logic(self) -> None:
        """A suspect verdict on a body that was rewritten mid-replay must not
        delete the new body on the strength of the old one's streak. The fire
        is still finished by the agent: the result was not trusted either way."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_suspect_replay("empty"))
        harness.record_run_outcome = AsyncMock(return_value=None)

        await _fire(harness)

        harness.delete_for_workflow.assert_not_awaited()
        harness.chat.assert_awaited_once()
        harness.add_messages.assert_not_awaited()
        warnings = [
            call
            for call in harness.log.warning.call_args_list
            if "not recorded" in str(call.args[0])
        ]
        assert len(warnings) == 1
        assert warnings[0].kwargs["revision"] == 0


class _LockedReplayHarness(_Harness):
    """The real execute_workflow_as_playbook with its I/O and lock seams mocked.

    The base harness stubs the replay function whole, which is right for the
    path-choice tests and useless here: the lock is taken inside it.
    """

    def __init__(self, workflow: Workflow, *, lock_free: bool, holder: str = "") -> None:
        super().__init__(workflow)
        self.calls: list[str] = []
        self.acquire = AsyncMock(side_effect=self._acquire)
        self.release = AsyncMock(side_effect=self._release)
        self.holder = AsyncMock(return_value=holder or None)
        self.run_playbook = AsyncMock(side_effect=self._run)
        self.notify = AsyncMock()
        self.increment = AsyncMock()
        self.get_user = AsyncMock(return_value={"user_id": workflow.user_id, "timezone": "UTC"})
        self.conversation = AsyncMock(return_value="conv_1")
        self._lock_free = lock_free
        self.replay_result: PlaybookRunResult | Exception = PlaybookRunResult(
            ok=True, text="Agenda sent.", trace=[RecordedCall(tool_name="list_events")]
        )

    async def _acquire(self, lock_key: str, lock_value: str) -> bool:
        self.calls.append("acquire")
        return self._lock_free

    async def _release(self, conversation_id: str, stream_id: str, task_id: str | None) -> None:
        self.calls.append("release")

    async def _run(self, *args: object, **kwargs: object) -> PlaybookRunResult:
        self.calls.append("run")
        if isinstance(self.replay_result, Exception):
            raise self.replay_result
        return self.replay_result

    def patches(self) -> list:
        return [
            patcher
            for patcher in super().patches()
            if patcher.attribute not in {"execute_workflow_as_playbook", "WorkflowService"}
        ] + [
            patch(
                f"{MODULE}.WorkflowService",
                MagicMock(increment_execution_count=self.increment),
            ),
            patch(f"{MODULE}.try_acquire_lock", self.acquire),
            patch(f"{MODULE}.release_lock_if_owned", self.release),
            patch(f"{MODULE}.get_lock_holder", self.holder),
            patch(f"{MODULE}.run_playbook", self.run_playbook),
            patch(f"{MODULE}.notification_service.create_notification", self.notify),
            patch(f"{MODULE}.get_user_by_id", self.get_user),
            patch(f"{MODULE}.get_or_create_workflow_conversation", self.conversation),
        ]

    def acquired_task_id(self) -> str:
        """The task id the replay stamped into its lock value."""
        self.acquire.assert_awaited_once()
        lock_value = str(self.acquire.await_args.args[1])
        stream_id, task_id = lock_value.split(":", 1)
        assert stream_id == "", "a replay has no stream; the value must still parse as one"
        return task_id


class TestReplayHoldsTheConversationLock:
    """Two fires of one workflow at the same moment both replayed its playbook.

    Seen live: two "Replayed 1 step(s)" executions, two results in the
    conversation, duplicate notifications. The agentic path cannot do this —
    call_executor takes the conversation's busy lock and queues the second
    dispatch — but the replay took no lock at all. It now holds the same lock
    for its whole duration and drops out when it is already held.
    """

    async def test_the_replay_locks_the_workflows_conversation_and_frees_it_after(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=True)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        assert harness.acquire.await_args.args[0] == f"{EXECUTOR_BUSY_PREFIX}conv_1"
        task_id = harness.acquired_task_id()
        harness.release.assert_awaited_once_with("conv_1", "", task_id)
        assert harness.calls == ["acquire", "run", "release"], (
            "the lock must cover the whole replay, not just its start"
        )
        assert harness.complete_execution.await_args.kwargs["status"] == "success"

    async def test_a_replay_that_raises_still_frees_the_lock(self) -> None:
        """A wedged lock would block every later fire of this workflow — replay
        and agent alike — until the TTL lapsed."""
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=True)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.replay_result = RuntimeError("tool exploded")

        await _fire(harness)

        harness.release.assert_awaited_once_with("conv_1", "", harness.acquired_task_id())
        assert harness.calls == ["acquire", "run", "release"]
        assert harness.complete_execution.await_args.kwargs["status"] == "failed"
        assert harness.complete_execution.await_args.kwargs["error_message"] == "tool exploded"

    async def test_a_held_lock_stops_the_replay_before_any_step_runs(self) -> None:
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        harness.run_playbook.assert_not_awaited()
        harness.chat.assert_not_awaited()
        harness.release.assert_not_awaited()
        harness.add_messages.assert_not_awaited()

    async def test_a_held_lock_is_recorded_as_a_fire_that_did_not_run(self) -> None:
        """Honest record: skipped, in plain words, with no lock value in the
        text a user reads (the holder goes to the log)."""
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        harness.complete_execution.assert_awaited_once()
        kwargs = harness.complete_execution.await_args.kwargs
        assert kwargs["status"] == "skipped"
        assert kwargs["summary"] == OVERLAPPED_SUMMARY
        assert kwargs["conversation_id"] == "conv_1"
        assert kwargs.get("trace") is None, "nothing ran, so there is nothing to replay from"
        assert "stream_9:task_9" not in kwargs["summary"]

    async def test_a_held_lock_counts_as_an_unsuccessful_fire(self) -> None:
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        harness.increment.assert_awaited_once_with(
            workflow.id, workflow.user_id, is_successful=False
        )

    async def test_a_held_lock_tells_the_user_nothing(self) -> None:
        """The run holding the lock delivers the result; a second notification
        of either kind would be the very duplicate this lock exists to stop."""
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        harness.notify.assert_not_awaited()
        harness.completion_notification.assert_not_awaited()
        harness.platform_delivery.assert_not_awaited()

    async def test_a_held_lock_leaves_the_playbooks_record_alone(self) -> None:
        """No outcome was reached, so none is written: a skipped fire must not
        reset a suspect streak or count as a run."""
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        harness.record_run_outcome.assert_not_awaited()
        harness.delete_for_workflow.assert_not_awaited()

    async def test_a_held_lock_is_visible_on_the_wide_event_with_the_holder(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        event: dict[str, object] = {}
        for entry in harness.log.set_ns.call_args_list:
            if entry.args and entry.args[0] == "workflow":
                event.update(entry.kwargs)
        assert event.get("overlapped") is True
        assert event.get("outcome") == "overlapped_in_flight_run"
        assert event.get("lock_holder") == "stream_9:task_9"
        warnings = [
            call
            for call in harness.log.warning.call_args_list
            if call.kwargs.get("lock_holder") == "stream_9:task_9"
        ]
        assert warnings, "the skip must be logged with the holder's lock value"
        assert all(call.kwargs.get("conversation_id") == "conv_1" for call in warnings)

    async def test_a_held_lock_still_arms_the_next_occurrence(self) -> None:
        workflow = _workflow().model_copy(update={"repeat": "*/5 * * * *", "activated": True})
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.scheduler.claim_task_for_execution = AsyncMock(return_value=True)

        with ExitStack() as stack:
            for patcher in harness.patches():
                stack.enter_context(patcher)
            await execute_workflow_by_id(
                {},
                workflow.id or "",
                {
                    "trigger_type": TriggerType.SCHEDULE.value,
                    "scheduled_for": datetime.now(UTC).timestamp(),
                },
            )

        harness.scheduler.handle_recurring_task.assert_awaited_once()


class TestAFreshPlaybookIsAuditedAgainstItsOwnRun:
    """The fire that writes a playbook checks the frozen calls against what they
    returned in that very run, so a playbook frozen on emptiness is distrusted
    before it is ever replayed."""

    async def test_an_agent_run_that_froze_an_empty_fetch_marks_it_suspect(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        written = _playbook(workflow).model_copy(
            update={"steps": [PlaybookStep(id="mail", tool="GMAIL_FETCH_MESSAGES", args={})]}
        )
        harness.chat = AsyncMock(
            return_value=(
                "conv_1",
                [
                    RecordedCall(
                        tool_name="GMAIL_FETCH_MESSAGES",
                        result_digest='{"data": {"messages": []}, "successful": true}',
                    ),
                    RecordedCall(
                        tool_name="write_playbook",
                        result_digest='{"success": true, "data": {"playbook_id": "pb_1"}}',
                    ),
                ],
            )
        )
        harness.get_for_workflow = AsyncMock(side_effect=[None, written])

        await _fire(harness)

        harness.record_run_outcome.assert_awaited_once()
        assert harness.record_run_outcome.await_args.args[2].status is PlaybookRunStatus.SUSPECT
        assert harness.record_run_outcome.await_args.kwargs["playbook_id"] == written.playbook_id

    async def test_an_agent_run_that_wrote_nothing_records_no_outcome(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)

        await _fire(harness)

        harness.record_run_outcome.assert_not_awaited()


class TestAFireCutOffByTheJobTimeoutIsRecorded:
    """Seen live: a same-fire heal ran into the worker's 30-minute job timeout
    (three model calls stalled for minutes each). ARQ cancels the job, which
    arrives as CancelledError, not Exception, so the execution record stayed
    "running" forever and the next occurrence was never re-armed."""

    async def test_the_execution_is_failed_with_the_reason_and_the_cancel_propagates(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.chat = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await _fire(harness)

        harness.complete_execution.assert_awaited_once()
        kwargs = harness.complete_execution.await_args.kwargs
        assert kwargs["status"] == "failed"
        assert "stopped after 30 minutes" in kwargs["error_message"]


class TestReviewFixes:
    async def test_a_heal_runs_rewrite_is_not_audited_for_emptiness_again(self) -> None:
        """A quiet source: the heal probes broadly, confirms nothing is there
        and rewrites the same sequence. Auditing that rewrite would send every
        later fire back to the agent for good."""
        workflow = _workflow()
        harness = _Harness(workflow)
        distrusted = _distrusted(workflow)
        rewritten = distrusted.model_copy(
            update={
                "last_run_status": PlaybookRunStatus.NOT_RUN,
                "revision": distrusted.revision + 1,
                "steps": [PlaybookStep(id="mail", tool="GMAIL_FETCH_MESSAGES", args={})],
            }
        )
        harness.get_for_workflow = AsyncMock(side_effect=[distrusted, rewritten])
        harness.chat = AsyncMock(
            return_value=(
                "conv_1",
                [
                    RecordedCall(
                        tool_name="GMAIL_FETCH_MESSAGES",
                        result_digest='{"data": {"messages": []}, "successful": true}',
                    ),
                    RecordedCall(
                        tool_name="write_playbook",
                        result_digest='{"success": true, "data": {"playbook_id": "pb_1"}}',
                    ),
                ],
            )
        )

        await _fire(harness)

        assert harness.summary() == HEAL_RUN_SUMMARY
        harness.record_run_outcome.assert_not_awaited()

    async def test_the_same_fire_handover_after_a_suspect_replay_spends_a_heal_attempt(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(
            return_value=(
                "conv_1",
                PlaybookRunResult(
                    ok=True,
                    text="",
                    trace=[RecordedCall(tool_name="list_events", replayed=True)],
                    completed=["events (list_events {}) -> []"],
                    llm_calls=0,
                    suspect="list_events was empty",
                    suspect_source="record",
                ),
            )
        )
        harness.record_run_outcome = AsyncMock(
            return_value=playbook.model_copy(
                update={
                    "last_run_status": PlaybookRunStatus.SUSPECT,
                    "suspect_streak": 1,
                }
            )
        )

        await _fire(harness)

        harness.chat.assert_awaited_once()
        harness.increment_heal_attempts.assert_awaited_once_with(
            workflow.id,
            workflow.user_id,
            playbook_id=playbook.playbook_id,
            revision=playbook.revision,
        )

    async def test_a_job_timeout_records_the_playbook_run_as_failed(self) -> None:
        """The cancelled replay may have run its side effects; the next fire must
        heal with that on record, not replay them again as if nothing happened."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await _fire(harness)

        harness.record_run_outcome.assert_awaited_once()
        outcome = harness.record_run_outcome.await_args.args[2]
        assert outcome.status is PlaybookRunStatus.FAILED
        assert "stopped after" in outcome.reason

    def test_the_fallback_note_bounds_each_completed_line(self) -> None:
        result = PlaybookRunResult(
            ok=False,
            text="",
            trace=[],
            completed=["events (list_events {}) -> " + "x" * 10_000],
            failure="stopped",
            llm_calls=0,
        )

        note = _fallback_note(result)

        assert len(note) < 3_000
        assert "x" * 200 in note


class TestOnlyTheRecordsSuspectCountsTowardDeletion:
    async def test_a_record_suspect_counts(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_suspect_replay("empty", source="record"))

        await _fire(harness)

        assert harness.record_run_outcome.await_args.args[2].counts_toward_streak is True

    async def test_the_narrations_suspect_sends_the_fire_to_the_agent_but_does_not_count(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(
            return_value=_suspect_replay("the model's own take", source="narration")
        )

        await _fire(harness)

        assert harness.record_run_outcome.await_args.args[2].counts_toward_streak is False
        harness.chat.assert_awaited_once()
        harness.delete_for_workflow.assert_not_awaited()


async def _fire_with_context(harness: _Harness, context: dict[str, object]) -> str:
    """Fire the workflow with a caller-supplied trigger context."""
    with ExitStack() as stack:
        for patcher in harness.patches():
            stack.enter_context(patcher)
        return await execute_workflow_by_id({}, harness.workflow.id or "", context)


#: What ``_run_workflow`` hands the agent for a fire with no extra context.
AGENT_USER = {"user_id": "u_1"}


@pytest.mark.unit
class TestTheFallbackBriefTheAgentReads:
    """The brief is the only thing standing between a stopped replay and a
    second copy of every side effect, so its wording is a contract."""

    def test_a_line_at_the_bound_is_left_whole_and_the_next_one_is_cut(self) -> None:
        at_bound = "a" * FALLBACK_LINE_MAX_CHARS
        result = PlaybookRunResult(ok=False, completed=[at_bound, at_bound + "a"], failure="boom")

        note = _fallback_note(result)

        assert f"- {at_bound}\n- {at_bound}..." in note

    def test_a_stopped_replay_that_did_nothing_says_so_in_both_slots(self) -> None:
        result = PlaybookRunResult(ok=False, text="", trace=[], completed=[], failure=None)

        note = _fallback_note(result)

        assert note == wrap_agent_payload(
            AgentTag.PLAYBOOK_FALLBACK,
            PLAYBOOK_FALLBACK_TEMPLATE.format(
                failure="The replay stopped without saying why.", completed="- nothing"
            ),
        )

    def test_a_flagged_replay_that_gave_no_reason_says_so(self) -> None:
        result = PlaybookRunResult(ok=True, text="Done.", trace=[], completed=[], suspect=None)

        note = _fallback_note(result)

        # ``ok`` with no suspect still routes through the suspect template here:
        # the caller only builds a note for a replay it did not trust.
        assert note == wrap_agent_payload(
            AgentTag.PLAYBOOK_FALLBACK,
            PLAYBOOK_SUSPECT_FALLBACK_TEMPLATE.format(
                reason="no reason was recorded", completed="- nothing"
            ),
        )

    def test_each_completed_step_is_its_own_line(self) -> None:
        result = PlaybookRunResult(
            ok=False,
            text="",
            trace=[],
            completed=["read calendar", "drafted mail"],
            failure="boom",
        )

        note = _fallback_note(result)

        assert "- read calendar\n- drafted mail" in note

    def test_the_brief_is_framed_as_the_playbook_fallback_channel(self) -> None:
        """The tag is how the agent tells this block from the user's own words."""
        result = PlaybookRunResult(ok=False, text="", trace=[], completed=[], failure="boom")

        note = _fallback_note(result)

        body = note.removeprefix(f"<{AgentTag.PLAYBOOK_FALLBACK}>\n").removesuffix(
            f"\n</{AgentTag.PLAYBOOK_FALLBACK}>\n"
        )
        assert body != note, "the brief must be framed in the playbook-fallback tag"
        assert note == wrap_agent_payload(AgentTag.PLAYBOOK_FALLBACK, body)


@pytest.mark.asyncio
class TestEveryFireIsChargedAndLookedUpForItsOwnOwner:
    async def test_the_fire_is_charged_once_for_this_user_against_the_run_quota(
        self,
    ) -> None:
        """One fire, one execution charged — and against the workflow's owner,
        never a stray id: the charge is what stops a runaway schedule."""
        workflow = _workflow()
        harness = _Harness(workflow)

        await _fire(harness)

        assert harness.tiered_limit.await_args_list == [call("u_1", "trigger_workflow_executions")]

    async def test_the_shortcut_is_looked_up_for_this_workflow_and_this_user(
        self,
    ) -> None:
        """A lookup keyed on the wrong id would replay someone else's shortcut."""
        workflow = _workflow()
        harness = _Harness(workflow)

        await _fire(harness)

        assert harness.get_for_workflow.await_args_list == [call("wf_1", "u_1")]

    async def test_a_lookup_failure_names_itself_and_hands_the_fire_over_unchanged(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(side_effect=ConnectionError("mongo away"))

        await _fire(harness)

        harness.log.warning.assert_any_call(
            f"{LogTag.WORKFLOW} playbook lookup failed; running the workflow agentically",
            workflow_id="wf_1",
            error_type="ConnectionError",
        )
        assert harness.chat.await_args_list == [call(workflow, AGENT_USER, {})]
        assert harness.summary() == AGENT_RUN_SUMMARY


@pytest.mark.asyncio
class TestDiscardingAShortcutSaysWhichOneAndWhy:
    """A discard is silent data loss unless the log names the playbook and the
    reason — that pair is how a replay regression is traced back in production."""

    async def test_a_stale_shortcut_is_deleted_named_and_the_agent_takes_the_fire(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow, stale=True))

        await _fire(harness)

        harness.delete_for_workflow.assert_awaited_once_with("wf_1", "u_1")
        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook discarded",
            workflow_id="wf_1",
            playbook_id="pb_1",
            reason="stale_workflow_hash",
        )
        assert harness.playbook_event() == {
            "mode": "agent",
            "reason": "stale_workflow_hash",
            "playbook_id": "pb_1",
            "llm_calls": 0,
        }
        assert harness.chat.await_args_list == [call(workflow, AGENT_USER, {})]
        assert harness.summary() == SHORTCUT_DISCARDED_SUMMARY

    async def test_a_delete_that_fails_says_the_shortcut_stays_on_file(self) -> None:
        """The delete failing costs the next check, not this run — but a silent
        failure would leave a stale playbook nobody knows is still there."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow, stale=True))
        harness.delete_for_workflow = AsyncMock(side_effect=ConnectionError("mongo away"))

        await _fire(harness)

        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook delete failed; it stays on file for now",
            workflow_id="wf_1",
            playbook_id="pb_1",
            reason="stale_workflow_hash",
            error_type="ConnectionError",
        )
        assert harness.summary() == SHORTCUT_DISCARDED_SUMMARY

    async def test_an_exhausted_shortcut_is_discarded_with_its_attempt_count(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(
            return_value=_distrusted(workflow, attempts=PLAYBOOK_HEAL_ATTEMPT_LIMIT)
        )

        await _fire(harness)

        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook discarded",
            workflow_id="wf_1",
            playbook_id="pb_1",
            reason="heal_attempts_exhausted",
            heal_attempts=PLAYBOOK_HEAL_ATTEMPT_LIMIT,
        )
        assert harness.playbook_event() == {
            "mode": "agent",
            "reason": "heal_attempts_exhausted",
            "playbook_id": "pb_1",
            "heal_attempts": PLAYBOOK_HEAL_ATTEMPT_LIMIT,
            "llm_calls": 0,
        }
        assert harness.chat.await_args_list == [call(workflow, AGENT_USER, {})]
        assert harness.summary() == AGENT_RUN_SUMMARY


@pytest.mark.asyncio
class TestTheHealRunCarriesTheFireItWasGiven:
    async def test_the_heal_event_names_the_body_its_status_and_its_attempt_count(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_distrusted(workflow))

        await _fire(harness)

        assert harness.playbook_event() == {
            "mode": "agent",
            "reason": "heal",
            "playbook_id": "pb_1",
            "last_run_status": PlaybookRunStatus.SUSPECT.value,
            "heal_attempts": 0,
            "llm_calls": 0,
        }
        assert harness.chat.await_args_list == [call(workflow, AGENT_USER, {})]
        assert harness.summary() == HEAL_RUN_SUMMARY


@pytest.mark.asyncio
class TestTheReplayIsHandedTheFireItWasGiven:
    async def test_the_replay_gets_the_workflow_the_user_the_trigger_and_the_playbook(
        self,
    ) -> None:
        """Dropping any one of these replays the wrong thing for the wrong
        person, or replays with no trigger payload at all."""
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(
            return_value=(
                "conv_1",
                PlaybookRunResult(ok=True, text="Agenda sent.", trace=[]),
            )
        )

        await _fire(harness)

        assert harness.playbook_run.await_args_list == [call(workflow, AGENT_USER, {}, playbook)]


def _trusted_replay() -> tuple[str, PlaybookRunResult]:
    return (
        "conv_1",
        PlaybookRunResult(
            ok=True,
            text="Agenda sent.",
            trace=[RecordedCall(tool_name="list_events")],
            llm_calls=1,
        ),
    )


@pytest.mark.asyncio
class TestATrustedReplayWritesTheTurnAndTellsTheUser:
    async def test_the_turn_carries_this_replays_own_result(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        _, result = _trusted_replay()
        harness.playbook_run = AsyncMock(return_value=("conv_1", result))

        await _fire(harness)

        assert harness.add_messages.await_args_list == [
            call(
                conversation_id="conv_1",
                user_id="u_1",
                workflow=workflow,
                response="Agenda sent.",
                trace=result.trace,
                playbook=playbook,
            )
        ]
        assert harness.summary() == REPLAY_SUMMARY

    async def test_the_result_reaches_the_users_platforms_as_this_workflows_own(
        self,
    ) -> None:
        """The origin line is what a user sees in Slack/Telegram; a replay must
        be indistinguishable from an agent run there."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_trusted_replay())

        await _fire(harness)

        assert harness.platform_delivery.await_args_list == [
            call(
                user=AGENT_USER,
                user_id="u_1",
                notification_text="Agenda sent.",
                origin='workflow "Daily agenda" (id wf_1)',
            )
        ]

    async def test_an_outcome_the_playbook_no_longer_matches_is_reported_not_swallowed(
        self,
    ) -> None:
        """``record_run_outcome`` answering None means the body changed mid-run.
        Without the warning naming the revision, that is invisible."""
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_trusted_replay())

        await _fire(harness)

        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook replay outcome not recorded; the playbook changed mid-run",
            workflow_id="wf_1",
            playbook_id="pb_1",
            revision=playbook.revision,
            outcome=PlaybookRunStatus.SUCCESS.value,
        )


@pytest.mark.asyncio
class TestAnUntrustedReplayHandsOverWithItsRecord:
    async def test_a_stopped_replay_stamps_the_agent_takeover_on_the_event(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        _, result = _stopped_replay()
        harness.playbook_run = AsyncMock(return_value=("conv_1", result))

        await _fire(harness)

        assert harness.playbook_event() == {
            "mode": "agent",
            "reason": "replay_stopped",
            "playbook_id": "pb_1",
            "llm_calls": result.llm_calls,
            "outcome": PlaybookRunStatus.FAILED.value,
        }
        assert harness.summary() == REPLAY_STOPPED_SUMMARY
        # The hand-off was a heal run too, so it spends an attempt on this body.
        harness.increment_heal_attempts.assert_awaited_once_with(
            "wf_1", "u_1", playbook_id="pb_1", revision=_playbook(workflow).revision
        )

    async def test_a_flagged_replay_names_the_reason_everywhere_it_lands(self) -> None:
        """The reason reaches three places — the wide event, the warning, and
        the summary the workflow's owner reads — and the summary drops only a
        trailing full stop so it reads as one sentence."""
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        # Ends in a letter the strip must leave alone; only "." is trailing noise.
        reason = "the record's check flagged step X"
        _, result = _suspect_replay(reason)
        harness.playbook_run = AsyncMock(return_value=("conv_1", result))
        harness.record_run_outcome = AsyncMock(return_value=_recorded(playbook, streak=1))

        await _fire(harness)

        assert harness.playbook_event() == {
            "mode": "agent",
            "reason": "replay_suspect",
            "playbook_id": "pb_1",
            "llm_calls": result.llm_calls,
            "outcome": PlaybookRunStatus.SUSPECT.value,
            "suspect_reason": reason,
            "disabled": False,
        }
        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook replay not trusted; the agent is finishing this run",
            workflow_id="wf_1",
            playbook_id="pb_1",
            reason=reason,
        )
        assert harness.summary() == REPLAY_FLAGGED_SUMMARY.format(reason=reason)
        harness.increment_heal_attempts.assert_awaited_once()

    async def test_a_trailing_full_stop_is_dropped_from_the_summarys_reason(
        self,
    ) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay("the mail body was empty."))
        harness.record_run_outcome = AsyncMock(return_value=_recorded(playbook, streak=1))

        await _fire(harness)

        assert harness.summary() == REPLAY_FLAGGED_SUMMARY.format(reason="the mail body was empty")

    async def test_the_agent_is_told_what_the_replay_already_did(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        _, result = _stopped_replay()
        harness.playbook_run = AsyncMock(return_value=("conv_1", result))

        await _fire(harness)

        assert harness.chat.await_args_list == [
            call(
                workflow,
                AGENT_USER,
                {PLAYBOOK_FALLBACK_CONTEXT_KEY: _fallback_note(result)},
            )
        ]

    async def test_a_disabled_shortcut_is_named_with_its_streak_and_spends_no_attempt(
        self,
    ) -> None:
        """Past the streak limit the body is gone, so an attempt counted against
        it would land nowhere — and the log is the only record it was dropped."""
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        reason = "the mail body was empty"
        harness.playbook_run = AsyncMock(return_value=_suspect_replay(reason))
        harness.record_run_outcome = AsyncMock(
            return_value=_recorded(playbook, streak=PLAYBOOK_SUSPECT_STREAK_LIMIT)
        )

        await _fire(harness)

        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook discarded",
            workflow_id="wf_1",
            playbook_id="pb_1",
            reason="suspect_streak_exhausted",
            suspect_streak=PLAYBOOK_SUSPECT_STREAK_LIMIT,
            suspect_reason=reason,
        )
        assert harness.playbook_event()["disabled"] is True
        harness.increment_heal_attempts.assert_not_awaited()

    async def test_a_fallback_that_is_queued_keeps_the_replays_calls_on_the_record(
        self,
    ) -> None:
        """The replay's calls happened; the queued task will read this record as
        its history, so losing them replays every side effect a second time."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_stopped_replay())
        harness.chat = AsyncMock(
            side_effect=WorkflowFireQueued(
                task_id="task_9",
                user_id="u_1",
                conversation_id="conv_1",
                trace=[RecordedCall(tool_name="call_executor")],
            )
        )

        await _fire(harness)

        trace = harness.complete_execution.await_args.kwargs["trace"]
        assert [recorded.tool_name for recorded in trace] == [
            "list_events",
            "call_executor",
        ]


@pytest.mark.asyncio
class TestTheReplayCompletionNotificationEdges:
    async def test_a_workflow_with_no_id_still_notifies_under_an_empty_id(self) -> None:
        """``workflow.id`` is optional on the model; the notification contract
        is a string, so the empty string — not a stand-in — is what it gets."""
        workflow = _workflow().model_copy(update={"id": None})
        completion = AsyncMock()
        with (
            patch(f"{MODULE}.deliver_result_to_platforms", AsyncMock()),
            patch(f"{MODULE}.send_workflow_completion_notification", completion),
        ):
            await _notify_replay_finished(workflow, AGENT_USER, "conv_1", "Agenda sent.")

        assert completion.await_args_list == [
            call(
                workflow_id="",
                workflow_title="Daily agenda",
                conversation_id="conv_1",
                user_id="u_1",
            )
        ]

    async def test_a_delivery_failure_is_named_and_never_fails_the_run(self) -> None:
        workflow = _workflow()
        log_seam = MagicMock()
        with (
            patch(
                f"{MODULE}.deliver_result_to_platforms",
                AsyncMock(side_effect=TimeoutError("platform down")),
            ),
            patch(f"{MODULE}.send_workflow_completion_notification", AsyncMock()),
            patch(f"{MODULE}.log", log_seam),
        ):
            await _notify_replay_finished(workflow, AGENT_USER, "conv_1", "Agenda sent.")

        log_seam.warning.assert_called_once_with(
            f"{LogTag.WORKER} Replay completion notification failed",
            workflow_id="wf_1",
            error="platform down",
            error_type="TimeoutError",
        )


@pytest.mark.asyncio
class TestTheReplayRunsAsTheWorkflowsOwnerInItsOwnConversation:
    async def test_the_conversation_is_this_workflows_own(self) -> None:
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=True)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        assert harness.conversation.await_args_list == [
            call(workflow_id="wf_1", user_id="u_1", workflow_title="Daily agenda")
        ]
        harness.get_user.assert_awaited_once_with("u_1")
        # The lock value a replay writes must be its own run's id, so the
        # release below can prove it still owns the lock it took.
        assert UUID(harness.acquired_task_id()).version == 4

    async def test_the_replay_carries_the_playbook_the_profile_and_the_trigger(
        self,
    ) -> None:
        """The replay's ``$now``/``$today`` come from this bag: a wrong zone or a
        blanked profile silently runs the user's day at the wrong hour."""
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=True)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.get_user = AsyncMock(
            return_value={
                "email": "ada@example.com",
                "name": "Ada",
                "timezone": "Asia/Kolkata",
            }
        )
        context = {"trigger_type": TriggerType.MANUAL.value, "note": "run it"}

        await _fire_with_context(harness, context)

        assert harness.run_playbook.await_args_list == [
            call(
                playbook,
                user=PlaybookUser(
                    email="ada@example.com",
                    name="Ada",
                    timezone=Timezone.parse("Asia/Kolkata").value,
                ),
                conversation_id="conv_1",
                trigger=context,
            )
        ]

    async def test_a_profile_with_no_name_or_mail_replays_with_empty_strings(
        self,
    ) -> None:
        """``PlaybookUser`` is a string contract — None would reach the prompt
        renderer as the literal "None"."""
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=True)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.get_user = AsyncMock(return_value={"timezone": "Asia/Kolkata"})

        await _fire(harness)

        replayed_as = harness.run_playbook.await_args.kwargs["user"]
        assert replayed_as.email == ""
        assert replayed_as.name == ""

    async def test_a_held_lock_names_the_holder_and_records_the_skip(self) -> None:
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        harness.holder.assert_awaited_once_with("conv_1")
        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook replay skipped; another run of this workflow "
            "holds its conversation",
            workflow_id="wf_1",
            conversation_id="conv_1",
            lock_holder="stream_9:task_9",
        )
        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Workflow fire overlapped an in-flight run — nothing executed",
            workflow_id="wf_1",
            conversation_id="conv_1",
            lock_holder="stream_9:task_9",
        )
        assert harness.complete_execution.await_args_list == [
            call(
                execution_id="exec_1",
                status="skipped",
                summary=OVERLAPPED_SUMMARY,
                conversation_id="conv_1",
            )
        ]

    async def test_an_unknown_holder_is_recorded_as_an_empty_string(self) -> None:
        """``get_lock_holder`` answers None once the lock lapses mid-check; the
        overlap signal's ``holder`` is a string, so None must not travel."""
        workflow = _workflow()
        harness = _LockedReplayHarness(workflow, lock_free=False)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))

        await _fire(harness)

        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Workflow fire overlapped an in-flight run — nothing executed",
            workflow_id="wf_1",
            conversation_id="conv_1",
            lock_holder="",
        )


@pytest.mark.asyncio
class TestTheZoneAWorkflowRunsIn:
    """Both run paths read ``$now``/``$today`` off this bag, and there is no
    request header in a worker — a silent UTC fallback runs someone's morning
    briefing in the middle of their night."""

    async def test_no_profile_and_no_schedule_zone_falls_back_to_utc_and_says_so(
        self,
    ) -> None:
        workflow = _workflow()
        log_seam = MagicMock()
        with (
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"user_id": "u_1"})),
            patch(f"{MODULE}.log", log_seam),
        ):
            resolved = await _resolve_workflow_user(workflow, "u_1")

        assert resolved["timezone"] == Timezone.utc().value
        log_seam.warning.assert_any_call(
            f"{LogTag.WORKER} Workflow agent time falling back to UTC; "
            "no real user/schedule timezone",
            workflow_id="wf_1",
            user_id="u_1",
        )

    async def test_a_profile_lookup_failure_leaves_the_run_with_only_its_user_id(
        self,
    ) -> None:
        workflow = _workflow()
        log_seam = MagicMock()
        with (
            patch(
                f"{MODULE}.get_user_by_id",
                AsyncMock(side_effect=ConnectionError("mongo away")),
            ),
            patch(f"{MODULE}.log", log_seam),
        ):
            resolved = await _resolve_workflow_user(workflow, "u_1")

        assert resolved == {"user_id": "u_1"}
        log_seam.warning.assert_any_call(
            f"{LogTag.WORKER} Could not resolve workflow timezone",
            user_id="u_1",
            workflow_id="wf_1",
            error_type="ConnectionError",
            error="mongo away",
        )


@pytest.mark.asyncio
class TestAFailureAfterAReplayIsStillTheWorkflowsOwn:
    async def test_the_failed_fire_is_counted_for_this_workflow_and_user(self) -> None:
        """The wrapped-with-trace failure path has its own call into the
        bookkeeping; a blank workflow there loses the count and the notice."""
        workflow = _workflow()
        harness = _Harness(workflow)
        increment = AsyncMock()
        harness.extra = [
            patch(
                f"{MODULE}.WorkflowService",
                MagicMock(increment_execution_count=increment),
            )
        ]
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_stopped_replay())
        harness.chat = AsyncMock(side_effect=RuntimeError("agent exploded"))

        with patch(f"{MODULE}.notification_service.create_notification", AsyncMock()):
            await _fire(harness)

        assert increment.await_args_list == [call("wf_1", "u_1", is_successful=False)]


@pytest.mark.asyncio
class TestTheDisabledFlagStartsFalseNotUnset:
    async def test_a_suspect_replay_whose_outcome_write_missed_still_reports_not_disabled(
        self,
    ) -> None:
        """``record_run_outcome`` answers None when the body changed mid-run, so
        the streak is unknown and nothing is dropped. The event must still say
        the shortcut is alive, not leave the field unset."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_suspect_replay("the mail body was empty"))
        harness.record_run_outcome = AsyncMock(return_value=None)

        await _fire(harness)

        assert harness.playbook_event()["disabled"] is False
        harness.delete_for_workflow.assert_not_awaited()


def _recurring(workflow: Workflow) -> Workflow:
    """The workflow shape a re-arm actually acts on: repeating and live."""
    return workflow.model_copy(
        update={"repeat": "*/5 * * * *", "activated": True, "occurrence_count": 0}
    )


SCHEDULE_CONTEXT: dict[str, object] = {"trigger_type": TriggerType.SCHEDULE.value}


@pytest.mark.asyncio
class TestARearmFailureAfterAnOverlapNamesTheWorkflow:
    async def test_the_error_line_carries_the_id_of_the_schedule_that_stalled(
        self,
    ) -> None:
        """A re-arm that fails silently stops a recurring workflow for good; the
        id is the only thing that ties the line back to which one."""
        workflow = _recurring(_workflow())
        harness = _LockedReplayHarness(workflow, lock_free=False, holder="stream_9:task_9")
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.scheduler.handle_recurring_task = AsyncMock(side_effect=RuntimeError("redis away"))

        await _fire_with_context(harness, SCHEDULE_CONTEXT)

        logged = [str(entry.args[0]) for entry in harness.log.error.call_args_list if entry.args]
        assert any("wf_1" in line for line in logged), logged


@pytest.mark.asyncio
class TestTheScheduleZoneIsTheFallbackForABlankProfile:
    """The profile wins only when it names a real zone; a blank or plain-UTC
    profile falls back to the zone the user picked for the schedule itself."""

    async def test_a_blank_profile_runs_in_the_schedules_own_zone(self) -> None:
        workflow = _workflow()
        workflow.trigger_config.timezone = "Asia/Kolkata"
        with (
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"user_id": "u_1"})),
            patch(f"{MODULE}.log", MagicMock()),
        ):
            resolved = await _resolve_workflow_user(workflow, "u_1")

        assert resolved["timezone"] == Timezone.parse("Asia/Kolkata").value

    async def test_a_plain_utc_profile_still_defers_to_the_schedules_zone(self) -> None:
        workflow = _workflow()
        workflow.trigger_config.timezone = "Asia/Kolkata"
        with (
            patch(
                f"{MODULE}.get_user_by_id",
                AsyncMock(return_value={"user_id": "u_1", "timezone": "UTC"}),
            ),
            patch(f"{MODULE}.log", MagicMock()),
        ):
            resolved = await _resolve_workflow_user(workflow, "u_1")

        assert resolved["timezone"] == Timezone.parse("Asia/Kolkata").value

    async def test_a_real_profile_zone_wins_over_the_schedules(self) -> None:
        workflow = _workflow()
        workflow.trigger_config.timezone = "Asia/Kolkata"
        with (
            patch(
                f"{MODULE}.get_user_by_id",
                AsyncMock(return_value={"user_id": "u_1", "timezone": "Europe/Lisbon"}),
            ),
            patch(f"{MODULE}.log", MagicMock()),
        ):
            resolved = await _resolve_workflow_user(workflow, "u_1")

        assert resolved["timezone"] == Timezone.parse("Europe/Lisbon").value

    async def test_a_blank_schedule_zone_is_not_treated_as_a_zone(self) -> None:
        """A stored "   " must read as "never picked one", not as a name to parse."""
        workflow = _workflow()
        workflow.trigger_config.timezone = "   "
        with (
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"user_id": "u_1"})),
            patch(f"{MODULE}.log", MagicMock()),
        ):
            resolved = await _resolve_workflow_user(workflow, "u_1")

        assert resolved["timezone"] == Timezone.utc().value


def _narration_failed_replay(reason: str) -> tuple[str, PlaybookRunResult]:
    """A replay whose steps all ran and whose end-of-run summary raised."""
    return (
        "conv_1",
        PlaybookRunResult(
            ok=True,
            text=f"The saved steps ran, but the summary could not be written ({reason}).",
            completed=["events (list_events) -> 12 events"],
            trace=[RecordedCall(tool_name="list_events")],
            narration_failed=reason,
            llm_calls=0,
        ),
    )


@pytest.mark.asyncio
class TestANarrationFailureIsADeliveredRunNotAFailedOne:
    """Prod: 13 of 15 failed playbooks had every step complete and only the
    end-of-run summary raise. Marked FAILED, the user got nothing and the next
    fire spent a ~20-call heal run repairing a sequence that had just worked."""

    REASON = "the narration raised TimeoutError: model"

    async def test_the_frozen_sequence_is_recorded_as_a_success(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_narration_failed_replay(self.REASON))

        await _fire(harness)

        harness.record_run_outcome.assert_awaited_once_with(
            workflow.id,
            workflow.user_id,
            PlaybookRunOutcome(PlaybookRunStatus.SUCCESS, reason=None, counts_toward_streak=True),
            playbook_id="pb_1",
            revision=0,
        )
        # SUCCESS is what keeps the next fire on the replay: a heal status there
        # would send it to the agent with the heal brief, at full agent cost.
        assert PlaybookRunStatus.SUCCESS not in HEAL_STATUSES
        harness.chat.assert_not_awaited()
        harness.delete_for_workflow.assert_not_awaited()
        harness.increment_heal_attempts.assert_not_awaited()

    async def test_the_user_reads_the_record_of_what_ran(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        _, result = _narration_failed_replay(self.REASON)
        harness.playbook_run = AsyncMock(return_value=("conv_1", result))

        await _fire(harness)

        assert harness.delivered_text() == result.text
        assert harness.platform_delivery.await_args.kwargs["notification_text"] == result.text

    async def test_the_execution_record_says_the_summary_is_the_part_that_is_missing(
        self,
    ) -> None:
        """The run is not a plain replay and not a stopped one; the workflows
        page has to say which of the two it was."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_narration_failed_replay(self.REASON))

        await _fire(harness)

        assert harness.summary() == REPLAY_NARRATION_FAILED_SUMMARY

    async def test_the_dead_model_call_is_still_named_on_the_wide_event(self) -> None:
        """Delivering the run is not the same as the call being fine: a fleet-wide
        narration outage has to stay visible even though no fire failed."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow))
        harness.playbook_run = AsyncMock(return_value=_narration_failed_replay(self.REASON))

        await _fire(harness)

        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook replayed but the narration failed; "
            "delivered the steps' record instead",
            workflow_id="wf_1",
            playbook_id="pb_1",
            reason=self.REASON,
        )


@pytest.mark.asyncio
class TestADiscardedShortcutLeavesARecordOnTheWorkflow:
    """``wf_0d05167369cf`` lost a working playbook and nothing said why: the log
    line ages out, and the workflow itself never knew it had one."""

    async def test_a_stale_shortcut_records_the_hash_reason(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow, stale=True))

        await _fire(harness)

        discard = harness.discard_record()
        assert (discard.playbook_id, discard.revision) == ("pb_1", 0)
        assert discard.reason == "stale_workflow_hash"
        assert discard.details == {}
        # Stamped in UTC, not on the worker's local clock: a naive timestamp
        # read back six months later says the wrong hour and cannot be compared
        # with anything else in the record.
        assert discard.at.tzinfo is UTC
        assert harness.update_workflow.await_args.args[:2] == ("wf_1", "u_1")

    async def test_an_exhausted_heal_records_the_attempts_it_spent(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(
            return_value=_distrusted(workflow, attempts=PLAYBOOK_HEAL_ATTEMPT_LIMIT)
        )

        await _fire(harness)

        discard = harness.discard_record()
        assert discard.reason == "heal_attempts_exhausted"
        assert discard.details == {"heal_attempts": str(PLAYBOOK_HEAL_ATTEMPT_LIMIT)}

    async def test_a_streak_that_ran_out_records_the_streak_and_what_flagged_it(self) -> None:
        workflow = _workflow()
        harness = _Harness(workflow)
        playbook = _playbook(workflow)
        harness.get_for_workflow = AsyncMock(return_value=playbook)
        harness.playbook_run = AsyncMock(return_value=_suspect_replay("the mail body was empty"))
        harness.record_run_outcome = AsyncMock(
            return_value=_recorded(playbook, streak=PLAYBOOK_SUSPECT_STREAK_LIMIT)
        )

        await _fire(harness)

        discard = harness.discard_record()
        assert discard.reason == "suspect_streak_exhausted"
        assert discard.details == {
            "suspect_streak": str(PLAYBOOK_SUSPECT_STREAK_LIMIT),
            "suspect_reason": "the mail body was empty",
        }

    async def test_a_write_that_fails_is_named_and_never_fails_the_fire(self) -> None:
        """The record is an explanation, not a precondition: losing it costs the
        answer six months from now, never the run happening today."""
        workflow = _workflow()
        harness = _Harness(workflow)
        harness.get_for_workflow = AsyncMock(return_value=_playbook(workflow, stale=True))
        harness.update_workflow = AsyncMock(side_effect=ConnectionError("mongo away"))

        await _fire(harness)

        harness.chat.assert_awaited_once()
        assert harness.summary() == SHORTCUT_DISCARDED_SUMMARY
        harness.log.warning.assert_any_call(
            f"{LogTag.WORKER} Playbook discard not recorded on the workflow",
            workflow_id="wf_1",
            playbook_id="pb_1",
            reason="stale_workflow_hash",
            error_type="ConnectionError",
        )
