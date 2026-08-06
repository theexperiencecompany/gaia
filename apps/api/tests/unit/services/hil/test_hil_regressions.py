"""Regressions for bugs found reviewing the HIL branch. Each test names the bug it pins.

These are the ones a passing suite did not catch, so each is written against the *shape*
of the mistake rather than the fix: a node replay that re-runs finished work, an
orchestration tool that fell through to the destructive classifier, and an auto-approved
call that parked on an approval nobody could answer.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from app.agents.core.subagents.subagent_runner import recover_from_checkpoint
from app.constants.general import WAIT_FOR_SUBAGENTS_NAME
from app.constants.hil import HIL_EXEMPT_TOOLS, HIL_PAUSING_TOOLS, HIL_STATUS_KWARG
from app.services.hil.gate import gate_tool_call
from app.services.hil.policy import has_pausing_sibling

from .conftest import USER_ID, ai_message_with_calls, make_record, make_request

GATE = "app.services.hil.gate"
POLICY = "app.services.hil.policy"


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
            result = await gate_tool_call(make_request(name=WAIT_FOR_SUBAGENTS_NAME), handler)

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


class TestAutoApprovedReplayNeverParks:
    """Bug: on a node replay the gate found the existing ``auto_approved`` record, skipped
    the judge, published nothing (the upsert no-ops), and then called ``interrupt()``
    anyway — parking the run on an approval with no pending record, no card, and no sweep
    pass that would ever resolve it. The conversation's executor lock was held for hours.
    """

    @pytest.fixture
    def replay(self):
        """The gate re-entered over a record for a call auto mode already ran."""
        with (
            patch(f"{GATE}.log"),
            patch(f"{GATE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{GATE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{GATE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(
                f"{GATE}.get_approval",
                new=AsyncMock(return_value=make_record(status="auto_approved")),
            ),
            patch(f"{GATE}.publish_approval_request", new=AsyncMock()) as card,
            patch(f"{GATE}.publish_auto_approval", new=AsyncMock()) as receipt,
            patch(f"{GATE}.judge_intent", new=AsyncMock()) as judge,
            patch(f"{GATE}.interrupt") as interrupt,
        ):
            yield {"card": card, "receipt": receipt, "judge": judge, "interrupt": interrupt}

    async def test_the_replay_does_not_park_on_an_unanswerable_approval(self, replay: dict) -> None:
        handler = AsyncMock()

        await gate_tool_call(make_request(), handler)

        replay["interrupt"].assert_not_called()
        replay["card"].assert_not_awaited()

    async def test_the_action_is_not_performed_a_second_time(self, replay: dict) -> None:
        # The other way this could fail: re-running the handler instead of parking. Both
        # are wrong — the action already happened and is irreversible by definition.
        handler = AsyncMock()

        result = await gate_tool_call(make_request(), handler)

        handler.assert_not_awaited()
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "already_ran"

    async def test_the_model_is_told_the_action_did_happen(self, replay: dict) -> None:
        # A refusal that reads as "did not happen" would make the model do it again by
        # another route. This is the one gate message that must confirm the action.
        result = await gate_tool_call(make_request(), AsyncMock())

        assert "WAS performed" in result.content

    async def test_no_second_judge_call_is_spent_on_the_replay(self, replay: dict) -> None:
        await gate_tool_call(make_request(), AsyncMock())

        replay["judge"].assert_not_awaited()
        replay["receipt"].assert_not_awaited()

    async def test_a_pending_record_still_falls_through_to_the_pause(self) -> None:
        # The short-circuit must be scoped to `auto_approved`. A PENDING record is the
        # normal ask-mode replay and must reach interrupt(), or the resume value it is
        # holding lands on the wrong call.
        with (
            patch(f"{GATE}.log"),
            patch(f"{GATE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{GATE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{GATE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{GATE}.get_approval", new=AsyncMock(return_value=make_record())),
            patch(f"{GATE}.publish_approval_request", new=AsyncMock()),
            patch(f"{GATE}.publish_approval_outcome", new=AsyncMock()),
            patch(f"{GATE}.remember_declined_call", new=AsyncMock()),
            patch(f"{GATE}.interrupt", return_value={"status": "denied"}) as interrupt,
        ):
            await gate_tool_call(make_request(), AsyncMock())

        interrupt.assert_called_once()
