"""Attacks on the HIL approval barrier (wait_for_subagents + background parking).

The barrier is what stands between "two subagents want to send things" and
"two things get sent twice, or never, or without asking". The invariants under
attack:

* the executor pauses ONCE per batch, never per approval;
* decided subagents are collected BEFORE any new pause;
* collection is stamped BEFORE the resume runs (a crash must not re-drive an
  approved irreversible action);
* a background subagent that pauses parks durably instead of raising;
* one subagent's failure never strands the rest of the batch.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background.subagent_runner import BackgroundHandoff, run_subagent_background
from app.agents.core.subagents.subagent_runner import SubagentOutcome
from app.agents.tools.wait_for_subagents_tool import _resolve_parked_batch
from app.constants.hil import HIL_BATCH_INTERRUPT_TYPE
from app.models.hil_models import HILApprovalStatus

BARRIER = "app.agents.tools.wait_for_subagents_tool"
RUNNER = "app.agents.core.background.subagent_runner"

CONV = "conv-1"
STREAM = "stream-1"


class FakePause(Exception):
    """Stands in for GraphInterrupt: interrupt() raises out of the node."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__("pause")
        self.payload = payload


def make_record(
    approval_id: str,
    status: HILApprovalStatus = HILApprovalStatus.PENDING,
    thread_id: str = "gmail_executor_conv-1",
    agent: str = "gmail",
) -> MagicMock:
    return MagicMock(
        approval_id=approval_id,
        status=status,
        subagent_thread_id=thread_id,
        subagent_agent_name=agent,
        summary=f"summary {approval_id}",
        integration_name=agent,
        tool_name="SEND",
        feedback=None,
        scope="once",
    )


def _interrupt_raising(payloads: list[dict[str, Any]]) -> MagicMock:
    def _raise(payload: dict[str, Any]) -> None:
        payloads.append(payload)
        raise FakePause(payload)

    return MagicMock(side_effect=_raise)


class TestBatchPause:
    async def test_two_pending_approvals_pause_the_executor_once_with_both(self) -> None:
        records = [make_record("a1"), make_record("a2", agent="slack")]
        payloads: list[dict[str, Any]] = []
        with (
            patch(
                f"{BARRIER}.list_parked_subagents_for_conversation", AsyncMock(return_value=records)
            ),
            patch(f"{BARRIER}.make_redis_stream_writer", MagicMock()),
            patch(f"{BARRIER}.resume_parked_subagent", AsyncMock()) as resume,
            patch(f"{BARRIER}.interrupt", _interrupt_raising(payloads)),
            pytest.raises(FakePause),
        ):
            await _resolve_parked_batch(CONV, {}, STREAM)

        # One pause carrying the WHOLE batch — never one pause per approval.
        assert len(payloads) == 1
        assert payloads[0]["type"] == HIL_BATCH_INTERRUPT_TYPE
        assert payloads[0]["approval_ids"] == ["a1", "a2"]
        # Nothing pending may be executed.
        assert resume.await_count == 0

    async def test_decided_subagents_are_collected_before_any_pause(self) -> None:
        decided = make_record("a1", status=HILApprovalStatus.APPROVED)
        pending = make_record("a2", status=HILApprovalStatus.PENDING, agent="slack")
        # First query: one decided, one pending. Second: only the pending left.
        listing = AsyncMock(side_effect=[[decided, pending], [pending]])
        payloads: list[dict[str, Any]] = []
        with (
            patch(f"{BARRIER}.list_parked_subagents_for_conversation", listing),
            patch(f"{BARRIER}.make_redis_stream_writer", MagicMock()),
            patch(f"{BARRIER}.mark_subagent_collected", AsyncMock()),
            patch(f"{BARRIER}.mark_resumed", AsyncMock()),
            patch(
                f"{BARRIER}.resume_parked_subagent",
                AsyncMock(return_value=SubagentOutcome(text="sent")),
            ) as resume,
            patch(f"{BARRIER}.append_bg_subagent_result", AsyncMock()) as append,
            patch(f"{BARRIER}.interrupt", _interrupt_raising(payloads)),
            pytest.raises(FakePause),
        ):
            await _resolve_parked_batch(CONV, {}, STREAM)

        assert resume.await_count == 1  # the approved one ran
        append.assert_awaited_once_with(CONV, "gmail", "sent")
        assert payloads[0]["approval_ids"] == ["a2"]  # then paused for the rest

    async def test_collection_is_stamped_before_the_resume_runs(self) -> None:
        # Crash-safety ordering: if the process dies mid-resume, a re-run must
        # find the record already collected — re-driving the thread re-sends.
        record = make_record("a1", status=HILApprovalStatus.APPROVED)
        order: list[str] = []

        async def _stamp(*_: Any) -> None:
            order.append("stamp")

        async def _resume(*_: Any, **__: Any) -> SubagentOutcome:
            order.append("resume")
            return SubagentOutcome(text="sent")

        listing = AsyncMock(side_effect=[[record], []])
        with (
            patch(f"{BARRIER}.list_parked_subagents_for_conversation", listing),
            patch(f"{BARRIER}.make_redis_stream_writer", MagicMock()),
            patch(f"{BARRIER}.mark_subagent_collected", AsyncMock(side_effect=_stamp)),
            patch(f"{BARRIER}.mark_resumed", AsyncMock()),
            patch(f"{BARRIER}.resume_parked_subagent", AsyncMock(side_effect=_resume)),
            patch(f"{BARRIER}.append_bg_subagent_result", AsyncMock()),
        ):
            await _resolve_parked_batch(CONV, {}, STREAM)

        assert order == ["stamp", "resume"]

    async def test_a_replayed_batch_with_all_decided_pauses_nothing(self) -> None:
        # The resume replay: every approval decided → collect all, return, no pause.
        records = [
            make_record("a1", status=HILApprovalStatus.APPROVED),
            make_record("a2", status=HILApprovalStatus.DENIED),
        ]
        listing = AsyncMock(side_effect=[records, []])
        with (
            patch(f"{BARRIER}.list_parked_subagents_for_conversation", listing),
            patch(f"{BARRIER}.make_redis_stream_writer", MagicMock()),
            patch(f"{BARRIER}.mark_subagent_collected", AsyncMock()),
            patch(f"{BARRIER}.mark_resumed", AsyncMock()),
            patch(
                f"{BARRIER}.resume_parked_subagent",
                AsyncMock(return_value=SubagentOutcome(text="done")),
            ) as resume,
            patch(f"{BARRIER}.append_bg_subagent_result", AsyncMock()),
            patch(f"{BARRIER}.interrupt", MagicMock()) as intr,
        ):
            await _resolve_parked_batch(CONV, {}, STREAM)

        assert resume.await_count == 2
        assert intr.call_count == 0

    async def test_a_resumed_subagent_that_parks_again_enters_the_next_round(self) -> None:
        record = make_record("a1", status=HILApprovalStatus.APPROVED)
        reparked = SubagentOutcome(text="", interrupt={"approval_id": "a1-next"})
        listing = AsyncMock(side_effect=[[record], []])
        with (
            patch(f"{BARRIER}.list_parked_subagents_for_conversation", listing),
            patch(f"{BARRIER}.make_redis_stream_writer", MagicMock()),
            patch(f"{BARRIER}.mark_subagent_collected", AsyncMock()),
            patch(f"{BARRIER}.mark_resumed", AsyncMock()),
            patch(f"{BARRIER}.resume_parked_subagent", AsyncMock(return_value=reparked)),
            patch(f"{BARRIER}.stamp_subagent_resume", AsyncMock()) as stamp,
            patch(f"{BARRIER}.append_bg_subagent_result", AsyncMock()) as append,
        ):
            await _resolve_parked_batch(CONV, {}, STREAM)

        stamp.assert_awaited_once_with(
            "a1-next",
            subagent_thread_id="gmail_executor_conv-1",
            subagent_agent_name="gmail",
        )
        assert append.await_count == 0  # no result yet — it parked again

    async def test_one_failing_resume_does_not_strand_the_rest(self) -> None:
        bad = make_record("a1", status=HILApprovalStatus.APPROVED)
        good = make_record("a2", status=HILApprovalStatus.APPROVED, agent="slack")
        listing = AsyncMock(side_effect=[[bad, good], []])
        outcomes = AsyncMock(side_effect=[RuntimeError("boom"), SubagentOutcome(text="posted")])
        with (
            patch(f"{BARRIER}.list_parked_subagents_for_conversation", listing),
            patch(f"{BARRIER}.make_redis_stream_writer", MagicMock()),
            patch(f"{BARRIER}.mark_subagent_collected", AsyncMock()) as collected,
            patch(f"{BARRIER}.mark_resumed", AsyncMock()),
            patch(f"{BARRIER}.resume_parked_subagent", outcomes),
            patch(f"{BARRIER}.append_bg_subagent_result", AsyncMock()) as append,
        ):
            await _resolve_parked_batch(CONV, {}, STREAM)

        assert collected.await_count == 2
        results = {call.args[1]: call.args[2] for call in append.await_args_list}
        assert "Error resuming gmail" in results["gmail"]
        assert results["slack"] == "posted"


class TestBackgroundParking:
    def _ctx(self) -> MagicMock:
        return MagicMock(
            agent_name="gmail",
            configurable={"conversation_id": CONV, "thread_id": "gmail_executor_conv-1"},
        )

    @pytest.fixture(autouse=True)
    def _live_executor(self):
        """Wake seam: a busy executor means landing work queues nothing."""
        with (
            patch(f"{RUNNER}.is_executor_busy", AsyncMock(return_value=True)),
            patch(f"{RUNNER}.enqueue_collection_run", AsyncMock()) as enqueue,
        ):
            self.enqueue = enqueue
            yield

    async def test_a_paused_subagent_parks_durably_instead_of_raising(self) -> None:
        paused = SubagentOutcome(text="", interrupt={"approval_id": "a1"})
        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock()),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(return_value=paused)),
            patch(f"{RUNNER}.stamp_subagent_resume", AsyncMock()) as stamp,
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock()) as append,
            patch(f"{RUNNER}.release_bg_integration", MagicMock()) as release,
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()) as decrement,
        ):
            await run_subagent_background(
                self._ctx(), STREAM, handoff=BackgroundHandoff(integration_id="gmail")
            )

        stamp.assert_awaited_once_with(
            "a1",
            subagent_thread_id="gmail_executor_conv-1",
            subagent_agent_name="gmail",
        )
        assert append.await_count == 0  # no result — the join collects it later
        release.assert_called_once_with(STREAM, "gmail")
        decrement.assert_called_once_with(STREAM)

    async def test_a_malformed_pause_becomes_a_loud_error_result(self) -> None:
        paused = SubagentOutcome(text="", interrupt={})  # no approval_id
        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock()),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(return_value=paused)),
            patch(f"{RUNNER}.stamp_subagent_resume", AsyncMock()) as stamp,
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock()) as append,
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()) as decrement,
        ):
            await run_subagent_background(self._ctx(), STREAM)

        assert stamp.await_count == 0  # nothing resumable was recorded
        assert "unresumable" in append.await_args.args[2]
        decrement.assert_called_once()

    async def test_a_landing_with_no_live_executor_queues_a_collection_turn(self) -> None:
        # The "rest" contract: the executor answered and moved on; this landing
        # must wake a collection turn or its result (or park) is stranded.
        done = SubagentOutcome(text="done")
        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock()),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(return_value=done)),
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock()),
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()),
            patch(f"{RUNNER}.is_executor_busy", AsyncMock(return_value=False)),
            patch(f"{RUNNER}.enqueue_collection_run", AsyncMock()) as enqueue,
        ):
            await run_subagent_background(self._ctx(), STREAM)

        enqueue.assert_awaited_once()

    async def test_a_landing_with_a_live_executor_queues_nothing(self) -> None:
        done = SubagentOutcome(text="done")
        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock()),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(return_value=done)),
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock()),
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()),
        ):
            await run_subagent_background(self._ctx(), STREAM)

        assert self.enqueue.await_count == 0

    async def test_the_start_card_carries_the_handoffs_whole_presentation(self) -> None:
        """The card the UI renders for a background handoff. Its fields come off
        the BackgroundHandoff, and the payload drops None values, so a lost
        icon_url or tool_category is a card rendered with neither."""
        writer = MagicMock()
        done = SubagentOutcome(text="done")
        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock(return_value=writer)),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(return_value=done)),
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock()),
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()),
        ):
            await run_subagent_background(
                self._ctx(),
                STREAM,
                handoff=BackgroundHandoff(
                    subagent_id="sa-1",
                    display_name="Gmail",
                    tool_category="comms",
                    icon_url="https://cdn.example/gmail.png",
                ),
            )

        start = writer.call_args_list[0].args[0]["subagent_start"]
        assert {k: v for k, v in start.items() if k != "started_at"} == {
            "subagent_id": "sa-1",
            "subagent_name": "Gmail",
            "agent_type": "handoff",
            "icon_url": "https://cdn.example/gmail.png",
            "tool_category": "comms",
        }

    async def test_a_recording_handoff_stores_its_result_with_the_call_record(self) -> None:
        """A workflow handoff's stored result is the subagent's text PLUS the
        record of the calls it actually made — that record is what the executor
        transcribes playbook steps from. Recording the wrong text, the wrong
        messages, or neither leaves the executor with nothing to transcribe."""
        messages = ("ai-message", "tool-message")
        done = SubagentOutcome(text="done", run_messages=messages)
        seen: list[tuple[Any, Any]] = []

        def _append_call_record(text: str, run_messages: Any) -> str:
            seen.append((text, run_messages))
            return f"{text}\n\n<call-record>"

        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock()),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(return_value=done)),
            patch(f"{RUNNER}.append_call_record", _append_call_record),
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock()) as append,
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()),
        ):
            await run_subagent_background(
                self._ctx(), STREAM, handoff=BackgroundHandoff(record_calls=True)
            )

        assert seen == [("done", messages)]
        append.assert_awaited_once_with(CONV, "gmail", "done\n\n<call-record>")

    async def test_a_handoff_that_records_nothing_stores_the_text_untouched(self) -> None:
        """The other side: a chat handoff has no playbook to feed, so its result
        is the subagent's own text and the recorder is never reached."""
        done = SubagentOutcome(text="done", run_messages=("ai-message",))
        recorder = MagicMock(side_effect=AssertionError("must not record"))

        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock()),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(return_value=done)),
            patch(f"{RUNNER}.append_call_record", recorder),
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock()) as append,
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()),
        ):
            await run_subagent_background(self._ctx(), STREAM)

        recorder.assert_not_called()
        append.assert_awaited_once_with(CONV, "gmail", "done")

    async def test_the_counter_decrements_even_when_everything_fails(self) -> None:
        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock()),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(side_effect=RuntimeError("x"))),
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock(side_effect=OSError("redis"))),
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()) as decrement,
        ):
            await run_subagent_background(self._ctx(), STREAM)  # must not raise

        decrement.assert_called_once_with(STREAM)

    async def test_a_wake_failure_does_not_raise_the_create_task_coroutine(self) -> None:
        """The wake check runs in the task's finally block, after the counter has
        already been decremented — a Redis blip here must not blow up the
        fire-and-forget coroutine (create_task swallows the exception silently,
        so an uncaught raise here is invisible except as a lost wake-up)."""
        done = SubagentOutcome(text="done")
        with (
            patch(f"{RUNNER}.make_redis_stream_writer", MagicMock()),
            patch(f"{RUNNER}.execute_subagent_stream", AsyncMock(return_value=done)),
            patch(f"{RUNNER}.append_bg_subagent_result", AsyncMock()),
            patch(f"{RUNNER}.decrement_pending_subagents", MagicMock()) as decrement,
            patch(f"{RUNNER}.is_executor_busy", AsyncMock(side_effect=RuntimeError("redis down"))),
        ):
            await run_subagent_background(self._ctx(), STREAM)  # must not raise

        decrement.assert_called_once_with(STREAM)
