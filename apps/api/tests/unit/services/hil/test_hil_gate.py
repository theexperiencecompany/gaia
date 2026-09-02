"""Attacks on the approval gate (app/services/hil/gate.py).

The gate is the last thing between a model's tool call and the real world. The attacks
that matter are the ones that make the tool *run* when it should not have:

* a malformed resume payload read as an approval;
* a gate that fails open when its own decision I/O breaks;
* a run whose identity is missing, so nothing gates it at all.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
import pytest

from app.constants.hil import HIL_STATUS_KWARG
from app.models.hil_models import HILApprovalStatus
from app.services.hil.bridge import ApprovalOutcome
from app.services.hil.gate import GateContext, _judge, _outcome_from_record, read_gate_context
from app.services.hil.intent import IntentDecision, JudgedCall
from app.services.hil.utils import GatedCall

from .conftest import (
    CONVERSATION_ID,
    STREAM_ID,
    USER_ID,
    make_record,
    make_request,
    make_tool,
    run_through_gate,
)

MODULE = "app.services.hil.gate"


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


@pytest.fixture(autouse=True)
def _no_prior_record():
    """The gate reads any existing record for this call before deciding. Default it to
    "none yet" — the first-pass case — so each test states only what it is about; the
    replay tests override it."""
    with patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=None)):
        yield


class _Handler:
    """Stands in for the real tool. Records whether the gate let it run — which is the
    only thing any of these tests actually cares about."""

    def __init__(self) -> None:
        self.ran = False

    async def __call__(self, request: Any) -> ToolMessage:
        self.ran = True
        return ToolMessage(content="the tool really ran", tool_call_id="call-1")


class TestTheDecisionComesFromTheRecord:
    """The record is the decision. The resume payload is a wake-up and nothing more.

    The gate used to read ``Command(resume=...)`` and had to defend against every
    malformed shape one could arrive in; it no longer looks at it at all. What matters
    now is that a stored status maps to the right fate, including the two that do not
    map to themselves.
    """

    def test_an_approval_is_honoured(self) -> None:
        # The positive control: if this fails, nothing can ever be approved.
        outcome = _outcome_from_record(make_record(status=HILApprovalStatus.APPROVED))
        assert outcome.status is HILApprovalStatus.APPROVED

    def test_auto_approved_reads_as_approved_so_the_call_still_runs(self) -> None:
        # It means "the user was not asked", NOT "the action already happened". Reading it
        # as anything else strands every auto-approved call unexecuted.
        outcome = _outcome_from_record(make_record(status=HILApprovalStatus.AUTO_APPROVED))
        assert outcome.status is HILApprovalStatus.APPROVED

    def test_abandoned_reads_as_denied(self) -> None:
        # The user moved on. Treating it as anything but a refusal would act on a request
        # they walked away from.
        outcome = _outcome_from_record(make_record(status=HILApprovalStatus.ABANDONED))
        assert outcome.status is HILApprovalStatus.DENIED

    def test_a_timeout_stays_a_timeout(self) -> None:
        # Not a denial: the user was away, not opposed, and the model is told so.
        outcome = _outcome_from_record(make_record(status=HILApprovalStatus.TIMEOUT))
        assert outcome.status is HILApprovalStatus.TIMEOUT

    def test_scope_and_feedback_ride_along(self) -> None:
        outcome = _outcome_from_record(
            make_record(
                status=HILApprovalStatus.DENIED, scope="always_tool", feedback="wrong recipient"
            )
        )
        assert outcome.feedback == "wrong recipient"
        assert outcome.scope == "always_tool"

    def test_only_pending_is_unsettled(self) -> None:
        # ``settled`` is what decides whether the gate reads a decision or asks for one,
        # so a status wrongly counted as settled would run an unapproved call.
        assert not HILApprovalStatus.PENDING.settled
        assert all(
            status.settled
            for status in HILApprovalStatus
            if status is not HILApprovalStatus.PENDING
        )


class TestGateContext:
    @pytest.mark.parametrize("missing", ["stream_id", "user_id", "conversation_id"])
    def test_a_run_missing_any_identity_field_cannot_be_gated(self, missing: str) -> None:
        configurable = {
            "stream_id": STREAM_ID,
            "user_id": USER_ID,
            "conversation_id": CONVERSATION_ID,
        }
        del configurable[missing]
        assert read_gate_context(make_request(configurable=configurable)) is None

    def test_a_background_run_is_identified_but_not_pausable(self) -> None:
        # No live client to approve, but it is NOT discarded: a gated call here must be
        # failed closed by the gate, not silently allowed. So it is returned, unpausable.
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "execution_mode": "background",
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.pausable is False

    def test_an_interactive_run_is_pausable(self) -> None:
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.pausable is True

    def test_an_empty_string_identity_is_treated_as_missing(self) -> None:
        request = make_request(
            configurable={"stream_id": "", "user_id": USER_ID, "conversation_id": CONVERSATION_ID}
        )
        assert read_gate_context(request) is None

    def test_conversation_id_is_read_rather_than_thread_id(self) -> None:
        # Inside the executor, thread_id is "executor_<conv>". Filing the approval under
        # it would put the card on a conversation the client never polls — the user would
        # never see it, and the run would hang to timeout.
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "thread_id": f"executor_{CONVERSATION_ID}",
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.conversation_id == CONVERSATION_ID

    @pytest.mark.parametrize("raw", ["not a list", None, 42, {"a": 1}])
    def test_malformed_user_messages_degrade_to_no_turns(self, raw: Any) -> None:
        # No turns → the judge cannot ground anything → it asks. Never a crash.
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "user_messages": raw,
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.user_messages == []

    def test_non_string_turns_are_dropped_rather_than_crashing_the_judge(self) -> None:
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "user_messages": ["send it", None, 42, {"role": "user"}, "to bob"],
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.user_messages == ["send it", "to bob"]


class TestGateFailsClosed:
    async def test_a_broken_policy_check_denies_instead_of_running_the_tool(self) -> None:
        # Attack: Redis/Mongo/registry falls over mid-run. The tool MUST NOT run.
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", side_effect=ConnectionError("mongo down")):
            result = await run_through_gate(make_request(), handler)

        assert handler.ran is False
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"

    async def test_a_broken_publish_denies_instead_of_running_the_tool(self) -> None:
        # If the user can't be shown the card, the call must not proceed unseen.
        handler = _Handler()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", side_effect=RuntimeError("redis down")),
        ):
            result = await run_through_gate(make_request(), handler)

        assert handler.ran is False
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"

    async def test_the_pause_is_never_swallowed_by_the_fail_closed_handler(self) -> None:
        # GraphInterrupt is control flow, not an error. If the broad `except` ever
        # catches it, every approval silently becomes a denial and HIL stops working.
        handler = _Handler()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", side_effect=GraphInterrupt(())),
            pytest.raises(GraphInterrupt),
        ):
            await run_through_gate(make_request(), handler)

        assert handler.ran is False

    async def test_a_tools_own_failure_is_not_converted_into_a_gate_denial(self) -> None:
        # The tool ran and blew up. That is a tool error, and the model must see it as
        # one — not as "the gate denied you", which would send the agent down the wrong
        # recovery path.
        async def exploding_handler(_: Any) -> ToolMessage:
            raise ValueError("the API rejected the request")

        with patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="allow")):
            with pytest.raises(ValueError, match="the API rejected the request"):
                await run_through_gate(make_request(), exploding_handler)


class TestGateBypasses:
    async def test_an_exempt_tool_runs_without_any_gate_check(self) -> None:
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock()) as policy:
            result = await run_through_gate(make_request(name="call_executor"), handler)

        assert handler.ran is True
        assert result.content == "the tool really ran"
        assert policy.await_count == 0

    async def test_an_ungateable_run_executes_the_tool(self) -> None:
        # A background/queued run has nobody to ask. It runs — by design.
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock()) as policy:
            await run_through_gate(make_request(configurable={}), handler)

        assert handler.ran is True
        assert policy.await_count == 0

    async def test_an_allowed_policy_runs_the_tool(self) -> None:
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="allow")):
            await run_through_gate(make_request(), handler)
        assert handler.ran is True


class TestDeclineMemory:
    async def test_a_call_the_user_already_declined_this_turn_is_auto_denied(self) -> None:
        # The retry loop: the executor never learns its subagent was declined, so it
        # tries again. Re-prompting the user for the same thing is the bug.
        handler = _Handler()
        declined = ApprovalOutcome(status="denied", feedback="wrong person")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=declined)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as publish,
        ):
            result = await run_through_gate(make_request(), handler)

        assert handler.ran is False
        assert publish.await_count == 0  # the user is NOT asked a second time
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"
        assert "wrong person" in result.content


class TestWhatTheIntentJudgeIsAskedAbout:
    """The judge rules on the call it is handed. A name, description, arguments or
    summary that arrives blank means it ruled on a different action than the one
    about to run — and an auto-approval on that ruling is the tool running
    unattended on evidence nobody checked."""

    async def test_the_whole_pending_call_reaches_the_judge(self) -> None:
        request = make_request(
            args={"to": "bob@example.com"},
            tool=make_tool(description="Send an email on the user's behalf."),
        )
        context = GateContext(
            stream_id=STREAM_ID,
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            user_messages=["send the deck to bob"],
            pausable=True,
        )
        call = GatedCall(name="send_email", id="call-1", args={"to": "bob@example.com"})
        allowed = IntentDecision(True, "You asked me to send Bob the deck.")

        with (
            patch(f"{MODULE}.has_pausing_sibling", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.judge_intent", new=AsyncMock(return_value=allowed)) as judge,
        ):
            decision = await _judge(
                request, context, call, None, "Send email — to: bob@example.com"
            )

        assert decision is allowed
        assert judge.await_args.kwargs["call"] == JudgedCall(
            tool_name="send_email",
            description="Send an email on the user's behalf.",
            args={"to": "bob@example.com"},
            summary="Send email — to: bob@example.com",
        )
