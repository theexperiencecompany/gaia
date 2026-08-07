"""Regressions for bugs found reviewing the HIL branch. Each test names the bug it pins.

These are the ones a passing suite did not catch, so each is written against the *shape*
of the mistake rather than the fix: a node replay that re-runs finished work, an
orchestration tool that fell through to the destructive classifier, and an auto-approved
call that parked on an approval nobody could answer.
"""

import asyncio
from contextlib import ExitStack
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphInterrupt
import pytest

from app.agents.core.subagents.subagent_runner import recover_from_checkpoint
from app.constants.general import WAIT_FOR_SUBAGENTS_NAME
from app.constants.hil import (
    HIL_EXEMPT_TOOLS,
    HIL_PAUSING_TOOLS,
    HIL_STATUS_KWARG,
    HIL_UNRESUMED_SWEEP_STATUSES,
)
from app.models.hil_models import HILApprovalStatus
from app.services.hil.approvals_store import clear_resume_item
from app.services.hil.intent import IntentDecision
from app.services.hil.policy import has_pausing_sibling
from app.services.hil.resolution import (
    cancel_conversation_approvals,
    resolve_approval,
    sweep_approvals,
)
from app.utils.errors import AppError

from .conftest import (
    CONVERSATION_ID,
    USER_ID,
    ai_message_with_calls,
    make_record,
    make_request,
    run_through_gate,
)

GATE = "app.services.hil.gate"
POLICY = "app.services.hil.policy"
RESOLUTION = "app.services.hil.resolution"
STORE = "app.services.hil.approvals_store"


def snapshot(next_nodes: tuple[str, ...] = (), messages: list[Any] | None = None) -> Any:
    """A LangGraph StateSnapshot as ``aget_state`` returns it.

    A thread that never ran has no checkpoint: empty ``next`` AND empty ``values``. A
    thread that FINISHED looks identical in ``next`` alone — which is the bug below.
    """
    return SimpleNamespace(
        next=next_nodes,
        values={"messages": messages} if messages is not None else {},
        interrupts=(),
    )


def ctx_with(snap: Any) -> Any:
    return SimpleNamespace(
        subagent_graph=SimpleNamespace(aget_state=AsyncMock(return_value=snap)),
        config={"configurable": {"thread_id": "gmail_executor_conv-1"}},
        configurable={"thread_id": "gmail_executor_conv-1", "conversation_id": "conv-1"},
    )


class TestFinishedSubagentIsNotDrivenTwice:
    """Bug: ``_parked_interrupt`` returned ``None`` for a thread that had FINISHED as well
    as one that had never run, so on an executor resume a completed blocking handoff was
    re-invoked from scratch — repeating every side effect its subagent had already caused.

    Trigger: one AI message with ``handoff(...)`` plus a gated tool. The handoff completes,
    the gated tool pauses, and LangGraph re-runs the whole node on resume.
    """

    async def test_a_finished_thread_returns_its_answer_instead_of_running_again(
        self,
    ) -> None:
        finished = snapshot(next_nodes=(), messages=[AIMessage(content="Bob is bob@example.com")])

        outcome = await recover_from_checkpoint(ctx_with(finished))

        assert outcome is not None, "a finished thread must be recovered, never re-run"
        assert outcome.paused is False
        assert outcome.text == "Bob is bob@example.com"

    async def test_a_thread_that_never_ran_is_still_started_normally(self) -> None:
        # The other half of the fix: recovering a never-run thread would mean the handoff
        # silently never happens.
        assert await recover_from_checkpoint(ctx_with(snapshot())) is None

    async def test_a_parked_thread_is_still_recovered_as_a_pause(self) -> None:
        parked = ctx_with(snapshot(next_nodes=("tools",), messages=[AIMessage(content="")]))
        parked.subagent_graph.aget_state.return_value.interrupts = (
            SimpleNamespace(value={"approval_id": "appr-1", "tool_name": "SEND"}),
        )

        outcome = await recover_from_checkpoint(parked)

        assert outcome is not None
        assert outcome.paused is True
        assert outcome.interrupt["approval_id"] == "appr-1"

    async def test_a_parked_thread_with_an_unreadable_payload_still_reads_as_paused(
        self,
    ) -> None:
        # An empty payload is treated downstream as a malformed approval and fails the run.
        # Reporting it as "finished" instead would let the executor carry on as if the
        # gated action had happened.
        outcome = await recover_from_checkpoint(ctx_with(snapshot(next_nodes=("tools",))))

        assert outcome is not None
        assert outcome.paused is True
        assert outcome.interrupt == {}

    async def test_a_finished_thread_with_no_text_is_still_not_re_run(self) -> None:
        # Falsey final content must not be mistaken for "never ran" — that is exactly the
        # conflation this bug was.
        outcome = await recover_from_checkpoint(
            ctx_with(snapshot(messages=[AIMessage(content="")]))
        )

        assert outcome is not None
        assert outcome.paused is False
        assert outcome.text == "Task completed."


class TestJoinToolIsNeverGated:
    """Bug: ``wait_for_subagents`` was absent from ``HIL_EXEMPT_TOOLS`` and is registered
    directly into the executor's tool dict rather than the ToolRegistry — so the gate sent
    it to the LLM destructive classifier, which fails CLOSED. A classifier outage would
    gate the very join that collects parked approvals.
    """

    def test_the_join_tool_is_exempt(self) -> None:
        assert WAIT_FOR_SUBAGENTS_NAME in HIL_EXEMPT_TOOLS

    async def test_the_gate_runs_it_without_resolving_any_policy(self) -> None:
        ran = False

        async def handler(_request: Any) -> ToolMessage:
            nonlocal ran
            ran = True
            return ToolMessage(content="collected", tool_call_id="call-1")

        with patch(f"{GATE}.resolve_policy", new=AsyncMock()) as policy:
            result = await run_through_gate(make_request(name=WAIT_FOR_SUBAGENTS_NAME), handler)

        assert ran is True
        assert result.content == "collected"
        policy.assert_not_awaited()

    def test_every_orchestration_tool_that_can_pause_is_also_exempt(self) -> None:
        # A pausing tool that is NOT exempt would be classified, and a fail-closed verdict
        # would gate it — which is the bug above, in whichever tool joins the set next.
        assert HIL_PAUSING_TOOLS <= HIL_EXEMPT_TOOLS


class TestExemptSiblingsThatPauseSuppressAutoApproval:
    """Bug: the sibling guard skipped every exempt tool, but ``handoff`` and
    ``wait_for_subagents`` are exempt AND can pause. A gated tool sharing a message with
    one of them auto-ran, then ran a SECOND time when the pause re-ran the whole node.
    """

    @pytest.fixture(autouse=True)
    def _registry(self):
        registry = SimpleNamespace(get_tool_meta=lambda _name: None)
        with (
            patch(f"{POLICY}.log"),
            patch(f"{POLICY}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(
                f"{POLICY}.get_hil_preferences",
                new=AsyncMock(return_value=MagicMock(tool_overrides={})),
            ),
            patch(f"{POLICY}.is_tool_destructive", new=AsyncMock(return_value=False)),
        ):
            yield

    @pytest.mark.parametrize("pausing_tool", ["handoff", WAIT_FOR_SUBAGENTS_NAME])
    async def test_a_pausing_sibling_blocks_auto_approval(self, pausing_tool: str) -> None:
        request = make_request(
            call_id="call-1",
            messages=[
                ai_message_with_calls(
                    {"id": "call-1", "name": "send_email", "args": {}},
                    {"id": "call-2", "name": pausing_tool, "args": {}},
                )
            ],
        )

        assert await has_pausing_sibling(request, USER_ID, "call-1") is True

    async def test_a_harmless_exempt_sibling_still_does_not_block(self) -> None:
        # The fix must not degrade into "any exempt sibling blocks", which would disable
        # auto mode for every turn that also searched memory.
        request = make_request(
            call_id="call-1",
            messages=[
                ai_message_with_calls(
                    {"id": "call-1", "name": "send_email", "args": {}},
                    {"id": "call-2", "name": "search_memory", "args": {}},
                )
            ],
        )

        assert await has_pausing_sibling(request, USER_ID, "call-1") is False

    async def test_the_gate_actually_consults_the_sibling_guard_before_auto_running(
        self,
    ) -> None:
        # The guard above is only worth having if the gate CALLS it. Every other test of
        # the whole-gate journeys patches has_pausing_sibling to a constant, so the seam
        # between _judge and the guard was never exercised — a tested component behind an
        # untested wire. Nothing is patched here but the I/O edges: the real guard runs,
        # sees the pausing `handoff` sibling, and must veto auto-approval even though the
        # judge says yes. If the wire is cut, the send happens now and AGAIN when the
        # sibling's pause re-runs the whole node ("one send became two").
        handler = AsyncMock()
        request = make_request(
            call_id="call-1",
            messages=[
                ai_message_with_calls(
                    {"id": "call-1", "name": "send_email", "args": {}},
                    {"id": "call-2", "name": "handoff", "args": {}},
                )
            ],
        )
        with (
            patch(f"{GATE}.log"),
            patch(f"{GATE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{GATE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{GATE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{GATE}.get_approval", new=AsyncMock(return_value=None)),
            patch(f"{GATE}.publish_approval_request", new=AsyncMock()) as card,
            patch(f"{GATE}.publish_decision", new=AsyncMock()),
            patch(f"{GATE}.publish_auto_approval", new=AsyncMock()) as receipt,
            patch(f"{GATE}.remember_declined_call", new=AsyncMock()),
            patch(
                f"{GATE}.judge_intent",
                new=AsyncMock(return_value=IntentDecision(True, "you said send it")),
            ) as judge,
            patch(f"{GATE}.interrupt", side_effect=GraphInterrupt(())) as interrupt,
        ):
            with pytest.raises(GraphInterrupt):
                await run_through_gate(request, handler)

        judge.assert_not_awaited()
        receipt.assert_not_awaited()
        handler.assert_not_awaited()
        card.assert_awaited_once()
        interrupt.assert_called_once()


class TestAnAutoApprovedRecordStillHasToRun:
    """``auto_approved`` means the user was not ASKED. It never meant the call ran.

    It used to: auto mode approved and executed in one pass, so a replay finding the
    record had to refuse (the action was irreversible and already done). Approvals are
    now settled in their own graph node and every tool — auto or not — is executed
    afterwards by the tool node, so a record that blocked execution would strand every
    auto-approved call unperformed.
    """

    @pytest.fixture
    def auto(self):
        """The tool node, over a record auto mode decided without asking."""
        with (
            patch(f"{GATE}.log"),
            patch(f"{GATE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{GATE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{GATE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(
                f"{GATE}.get_approval",
                new=AsyncMock(return_value=make_record(status=HILApprovalStatus.AUTO_APPROVED)),
            ),
            patch(f"{GATE}.publish_approval_request", new=AsyncMock()) as card,
            patch(f"{GATE}.publish_auto_approval", new=AsyncMock()) as receipt,
            patch(f"{GATE}.publish_decision", new=AsyncMock()) as settle,
            patch(f"{GATE}.set_tool_override", new=AsyncMock()),
            patch(f"{GATE}.judge_intent", new=AsyncMock()) as judge,
        ):
            yield {"card": card, "receipt": receipt, "judge": judge, "settle": settle}

    async def test_the_action_is_performed(self, auto: dict) -> None:
        handler = AsyncMock()

        await run_through_gate(make_request(), handler)

        handler.assert_awaited_once()

    async def test_no_second_judge_call_is_spent(self, auto: dict) -> None:
        # The judge is a non-deterministic LLM call and the decision is already made.
        await run_through_gate(make_request(), AsyncMock())

        auto["judge"].assert_not_awaited()
        auto["receipt"].assert_not_awaited()

    async def test_no_card_is_published_for_a_decision_already_made(self, auto: dict) -> None:
        await run_through_gate(make_request(), AsyncMock())

        auto["card"].assert_not_awaited()


class TestAPendingRecordParksInsteadOfRunning:
    """A record that exists but is undecided means the user has not answered yet.

    The call must neither run nor be refused: it parks, and the run resumes when the
    decision lands. Its siblings are unaffected — LangGraph persists the writes of the
    tasks that completed in the interrupting step (see
    ``tests/unit/agents/test_pause_checkpointing.py``), which is what makes pausing
    here safe rather than a source of double-execution.
    """

    @staticmethod
    def _edges():
        return (
            patch(f"{GATE}.log"),
            patch(f"{GATE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{GATE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{GATE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{GATE}.get_approval", new=AsyncMock(return_value=make_record())),
            patch(f"{GATE}.publish_approval_request", new=AsyncMock()),
            patch(f"{GATE}.publish_decision", new=AsyncMock()),
            patch(f"{GATE}.remember_declined_call", new=AsyncMock()),
        )

    async def test_it_parks_rather_than_running_or_refusing(self) -> None:
        handler = AsyncMock()
        with ExitStack() as stack:
            for ctx in self._edges():
                stack.enter_context(ctx)
            interrupt = stack.enter_context(
                patch(f"{GATE}.interrupt", side_effect=GraphInterrupt(()))
            )
            with pytest.raises(GraphInterrupt):
                await run_through_gate(make_request(), handler)

        interrupt.assert_called_once()
        handler.assert_not_awaited(), "an unanswered call must not run"

    async def test_the_judge_is_not_re_run_over_an_existing_record(self) -> None:
        # A record means a card is already up and the answer is the user's to give.
        # The judge is a non-deterministic LLM call: re-asking it on the replay could
        # return "aligned" and run the tool without the decision the user actually gave.
        handler = AsyncMock()
        with ExitStack() as stack:
            for ctx in self._edges():
                stack.enter_context(ctx)
            stack.enter_context(patch(f"{GATE}.resolve_policy", new=AsyncMock(return_value="auto")))
            stack.enter_context(patch(f"{GATE}.publish_auto_approval", new=AsyncMock()))
            stack.enter_context(patch(f"{GATE}.interrupt", side_effect=GraphInterrupt(())))
            judge = stack.enter_context(
                patch(
                    f"{GATE}.judge_intent",
                    new=AsyncMock(return_value=IntentDecision(True, "you said send it")),
                )
            )
            with pytest.raises(GraphInterrupt):
                await run_through_gate(make_request(), handler)

        judge.assert_not_awaited()
        handler.assert_not_awaited()


class TestAResumeWithNoDecisionFailsClosed:
    """The one path where ``interrupt()`` RETURNS instead of exiting the run.

    On a replay LangGraph hands the resume value back rather than raising, so execution
    continues past the pause. Normally the decision is already on the record and the
    call never reaches the pause again — ``resolve_approval`` marks the record decided
    before it dispatches the resume. But the gate must not assume that: the resume value
    is a wake-up, not a decision, and treating "we were woken" as "the user said yes"
    would run an irreversible action nobody approved.

    Found by mutation testing — replacing the post-pause re-read with a constant let an
    undecided call execute, and nothing in the suite noticed.
    """

    @staticmethod
    def _edges(record):
        return (
            patch(f"{GATE}.log"),
            patch(f"{GATE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{GATE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{GATE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{GATE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{GATE}.publish_approval_request", new=AsyncMock()),
            patch(f"{GATE}.publish_decision", new=AsyncMock()),
            patch(f"{GATE}.remember_declined_call", new=AsyncMock()),
            patch(f"{GATE}.set_tool_override", new=AsyncMock()),
        )

    async def test_a_still_pending_record_never_runs_the_tool(self) -> None:
        handler = AsyncMock()
        with ExitStack() as stack:
            for ctx in self._edges(make_record()):
                stack.enter_context(ctx)
            # Returns rather than raises: this IS the replay.
            stack.enter_context(patch(f"{GATE}.interrupt", return_value={"status": "approved"}))
            result = await run_through_gate(make_request(), handler)

        handler.assert_not_awaited(), "no record decision means no execution, ever"
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"

    async def test_an_approved_record_does_run_it(self) -> None:
        # The positive control: without this, "never runs" would also pass if the gate
        # were broken into refusing everything.
        handler = AsyncMock()
        with ExitStack() as stack:
            for ctx in self._edges(make_record(status=HILApprovalStatus.APPROVED)):
                stack.enter_context(ctx)
            stack.enter_context(patch(f"{GATE}.interrupt", return_value={"status": "approved"}))
            await run_through_gate(make_request(), handler)

        handler.assert_awaited_once()

    async def test_a_denied_resume_value_cannot_override_an_approved_record(self) -> None:
        # The reverse direction: the payload is not the decision in EITHER direction.
        handler = AsyncMock()
        with ExitStack() as stack:
            for ctx in self._edges(make_record(status=HILApprovalStatus.APPROVED)):
                stack.enter_context(ctx)
            stack.enter_context(patch(f"{GATE}.interrupt", return_value={"status": "denied"}))
            await run_through_gate(make_request(), handler)

        handler.assert_awaited_once()


async def drain_spawned_tasks() -> None:
    """_dispatch_resume spawns the run with create_task; let it actually start."""
    for _ in range(3):
        await asyncio.sleep(0)


class _ApprovalStore:
    """Stand-in for the approvals collection, keeping the one semantic that decides
    this: ``pending -> decided`` is conditional, so it happens at most once."""

    def __init__(self, *records: Any) -> None:
        self.records = {record.approval_id: record for record in records}

    async def get(self, approval_id: str) -> Any:
        return self.records.get(approval_id)

    async def list_pending(self, conversation_id: str) -> list[Any]:
        return [
            r
            for r in self.records.values()
            if r.conversation_id == conversation_id and r.status == "pending"
        ]

    async def mark_decided(self, approval_id: str, status: str, **kwargs: Any) -> bool:
        record = self.records.get(approval_id)
        if record is None or record.status != "pending":
            return False
        self.records[approval_id] = record.model_copy(
            update={"status": status, "decided_at": datetime.now(UTC), **kwargs}
        )
        return True

    async def clear_resume_item(self, approval_id: str) -> None:
        self.records[approval_id] = self.records[approval_id].model_copy(
            update={"resume_item": None}
        )

    async def list_decided_unresumed(self, grace: float) -> list[Any]:
        return [
            r
            for r in self.records.values()
            if r.status in HIL_UNRESUMED_SWEEP_STATUSES
            and r.resumed_at is None
            and r.resume_item is not None
        ]


class TestCancelledRunIsNotResurrectedByItsApproval:
    """cancel_executor stops the run and drops the busy lock, but neither reaches the
    approval record. Left pending it is a live Approve button — and a user-free timeout
    sweep — pointing at the run the user stopped, re-dispatched on a fresh stream that
    the original cancel flag never covered.
    """

    @staticmethod
    def _patches(store: _ApprovalStore, runner: AsyncMock) -> Any:
        return (
            patch(f"{RESOLUTION}.get_approval", new=AsyncMock(side_effect=store.get)),
            patch(
                f"{RESOLUTION}.list_pending_for_conversation",
                new=AsyncMock(side_effect=store.list_pending),
            ),
            patch(f"{RESOLUTION}.mark_decided", new=AsyncMock(side_effect=store.mark_decided)),
            patch(
                f"{RESOLUTION}.clear_resume_item",
                new=AsyncMock(side_effect=store.clear_resume_item),
            ),
            patch(
                f"{RESOLUTION}.list_decided_unresumed",
                new=AsyncMock(side_effect=store.list_decided_unresumed),
            ),
            patch(f"{RESOLUTION}.list_expired_pending", new=AsyncMock(return_value=[])),
            patch(
                f"{RESOLUTION}.prepare_run_from_item",
                new=AsyncMock(return_value=SimpleNamespace(run=None, task="t", configurable={})),
            ),
            patch(f"{RESOLUTION}.run_executor_background", new=runner),
            patch(f"{RESOLUTION}.claim_resume_dispatch", new=AsyncMock(return_value=True)),
            patch(f"{RESOLUTION}.release_resume_dispatch", new=AsyncMock()),
            patch(f"{RESOLUTION}.mark_resumed", new=AsyncMock()),
        )

    async def test_approving_afterwards_does_not_run_the_cancelled_action(self) -> None:
        store = _ApprovalStore(make_record(approval_id="a1"))
        runner = AsyncMock()
        with ExitStack() as stack:
            for p in self._patches(store, runner):
                stack.enter_context(p)

            await cancel_conversation_approvals(CONVERSATION_ID, USER_ID)
            with pytest.raises(AppError):
                await resolve_approval(approval_id="a1", user_id=USER_ID, kind="approve")
            await drain_spawned_tasks()

        assert runner.await_count == 0
        assert store.records["a1"].status == "abandoned"

    async def test_the_timeout_sweep_does_not_bring_the_cancelled_run_back(self) -> None:
        # No user involved at all: the sweep re-dispatches decided-but-unresumed records
        # from their resume_item, which is exactly what a cancelled record still had.
        store = _ApprovalStore(make_record(approval_id="a1"))
        runner = AsyncMock()
        with ExitStack() as stack:
            for p in self._patches(store, runner):
                stack.enter_context(p)

            await cancel_conversation_approvals(CONVERSATION_ID, USER_ID)
            counts = await sweep_approvals()
            await drain_spawned_tasks()

        assert counts == {"expired": 0, "redispatched": 0}
        assert runner.await_count == 0

    async def test_clearing_the_resume_context_actually_unsets_the_field(self) -> None:
        # The whole sweep exclusion rests on this one write. HILApprovalUpdate is applied
        # with exclude_unset, so an update built without the field sets nothing at all —
        # only an explicit None clears it.
        repository = AsyncMock()
        with patch(f"{STORE}.hil_approval_repository", repository):
            await clear_resume_item("a1")

        approval_id, update = repository.update.await_args.args
        assert approval_id == "a1"
        assert update.model_dump(exclude_unset=True) == {"resume_item": None}

    async def test_an_uncancelled_approval_still_resumes_normally(self) -> None:
        # The guard must not cost the feature: an ordinary approval still runs.
        store = _ApprovalStore(make_record(approval_id="a1"))
        runner = AsyncMock()
        with ExitStack() as stack:
            for p in self._patches(store, runner):
                stack.enter_context(p)

            await resolve_approval(approval_id="a1", user_id=USER_ID, kind="approve")
            await drain_spawned_tasks()

        assert runner.await_count == 1
        assert runner.await_args.kwargs["resume"].resume["status"] == "approved"
        # The id is what routes this decision to its own gate; a wrong one is discarded
        # by the matcher and the approved action never runs.
        assert runner.await_args.kwargs["resume"].resume["approval_id"] == "a1"
