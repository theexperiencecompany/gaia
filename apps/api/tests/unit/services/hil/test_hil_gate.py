"""Attacks on the approval gate (app/services/hil/gate.py).

The gate is the last thing between a model's tool call and the real world. The attacks
that matter are the ones that make the tool *run* when it should not have:

* a malformed resume payload read as an approval;
* a gate that fails open when its own decision I/O breaks;
* a run whose identity is missing, so nothing gates it at all.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call, patch

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
import pytest

from app.constants.hil import HIL_STATUS_KWARG
from app.models.hil_models import HILApprovalStatus
from app.services.hil import gate as gate_module
from app.services.hil.approvals_store import approval_id_for
from app.services.hil.bridge import ApprovalOutcome, build_summary
from app.services.hil.gate import _outcome_from_record, decide_tool_call, read_gate_context
from app.services.hil.intent import IntentDecision
from app.services.hil.prompts import (
    DENIED_TEMPLATE,
    GATE_ERROR_TEMPLATE,
    TIMEOUT_TEMPLATE,
    UNPAUSABLE_DENIAL_TEMPLATE,
)
from app.services.hil.utils import GatedCall, PriorCall, approval_window_label

from .conftest import (
    CONVERSATION_ID,
    STREAM_ID,
    USER_ID,
    ai_message_with_calls,
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


def _raising_interrupt(payload: Any) -> None:
    """Stand-in for ``langgraph.types.interrupt``, which raises ``GraphInterrupt`` with
    the payload but only inside a running graph. This is the same raise, off the hook."""
    raise GraphInterrupt(payload)


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
        assert context.stream_id == STREAM_ID
        assert context.user_id == USER_ID
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
        assert context.stream_id == STREAM_ID
        assert context.user_id == USER_ID
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
        assert result.content == GATE_ERROR_TEMPLATE.format(tool="send_email")
        assert gate_module.log.error.call_args.args[0] == "[HIL] Gate check failed for ; denying"
        assert gate_module.log.error.call_args.kwargs == {
            "name": "send_email",
            "error": "mongo down",
            "error_type": "ConnectionError",
        }

    async def test_a_graph_interrupt_from_the_policy_layer_is_not_converted_to_a_denial(
        self,
    ) -> None:
        # GraphInterrupt is control flow — the gate re-raises it from the policy layer
        # too. Swallowed here, a pausing sibling's interrupt would deny calls it was
        # never meant to judge.
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", side_effect=GraphInterrupt(())):
            with pytest.raises(GraphInterrupt):
                await run_through_gate(make_request(), handler)

        assert handler.ran is False

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
        assert result.content == GATE_ERROR_TEMPLATE.format(tool="send_email")
        assert gate_module.log.error.call_args.args[0] == "[HIL] Could not publish approval for ; denying"
        assert gate_module.log.error.call_args.kwargs == {
            "name": "send_email",
            "error": "redis down",
            "error_type": "RuntimeError",
        }

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
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=declined)) as recall,
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as publish,
        ):
            result = await run_through_gate(make_request(), handler)

        assert handler.ran is False
        assert publish.await_count == 0  # the user is NOT asked a second time
        recall.assert_awaited_once_with(STREAM_ID, "send_email", {})
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs == {HIL_STATUS_KWARG: "denied"}
        assert result.tool_call_id == "call-1"
        assert result.name == "send_email"
        assert result.content == DENIED_TEMPLATE.format(
            tool="send_email",
            feedback=" The user said: 'wrong person'.",
            waited=approval_window_label(),
        )
        assert gate_module.log.info.call_args.args[0] == "[HIL] auto-denying : declined earlier this turn"
        assert gate_module.log.info.call_args.kwargs == {"name": "send_email"}


class TestThePause:
    """An unanswered call pauses the run; on the replay the record decides.

    The gate's contract is that ``decide_tool_call`` raises ``GraphInterrupt`` for a
    call the user has not answered, and that on the resume replay the SAME call reads
    its decision off the record — never off the resume payload. These tests replay it
    the way the graph does: let the first pass interrupt, then call again with a
    decision now on the record.
    """

    async def test_an_unanswered_call_pauses_and_publishes_the_card(self) -> None:
        handler = _Handler()
        request = make_request(args={"to": "bob@example.com"})
        approval_id = approval_id_for(CONVERSATION_ID, "call-1")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")) as policy,
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)) as recall,
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="Gmail")) as integration,
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=None)) as get_record,
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as publish,
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
        ):
            with pytest.raises(GraphInterrupt):
                await run_through_gate(request, handler)

        assert handler.ran is False
        policy.assert_awaited_once_with(request, USER_ID, "send_email")
        get_record.assert_awaited_once_with(approval_id)
        recall.assert_awaited_once_with(STREAM_ID, "send_email", {"to": "bob@example.com"})
        integration.assert_awaited_once_with("send_email")
        publish.assert_awaited_once_with(
            approval_id=approval_id,
            stream_id=STREAM_ID,
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            tool_call=GatedCall(name="send_email", id="call-1", args={"to": "bob@example.com"}),
            summary=build_summary("send_email", {"to": "bob@example.com"}, "Gmail"),
            integration_name="Gmail",
        )

    async def test_the_interrupt_payload_names_the_call(self) -> None:
        # The card is matched to this exact call by its approval_id — a payload that
        # carries the wrong id, tool, summary or integration would mis-file the user's
        # decision or settle a sibling's card.
        payloads: list[dict[str, Any]] = []

        def capture(payload: dict[str, Any]) -> None:
            payloads.append(payload)

        handler = _Handler()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="Gmail")),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt", side_effect=capture),
        ):
            result = await run_through_gate(make_request(), handler)

        assert payloads == [
            {
                "type": "hil_approval",
                "approval_id": approval_id_for(CONVERSATION_ID, "call-1"),
                "tool_name": "send_email",
                "summary": build_summary("send_email", {}, "Gmail"),
                "integration_name": "Gmail",
            }
        ]
        assert handler.ran is False
        assert result.additional_kwargs == {HIL_STATUS_KWARG: "denied"}
        assert result.tool_call_id == "call-1"
        assert result.name == "send_email"
        assert result.content == UNPAUSABLE_DENIAL_TEMPLATE.format(tool="send_email")
        assert gate_module.log.error.call_args.args[0] == "[HIL] resumed with no decision on its record"
        assert gate_module.log.error.call_args.kwargs == {
            "approval_id": approval_id_for(CONVERSATION_ID, "call-1"),
            "tool_name": "send_email",
        }

    async def test_an_approved_record_applies_on_the_replay(self) -> None:
        handler = _Handler()
        request = make_request()
        record = make_record(status=HILApprovalStatus.APPROVED, feedback="yes do it")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.get_approval", new=AsyncMock(side_effect=[None, record])),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
            patch(f"{MODULE}.publish_decision", new=AsyncMock()) as publish,
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as override,
            patch(f"{MODULE}.remember_declined_call", new=AsyncMock()) as remember,
        ):
            with pytest.raises(GraphInterrupt):
                await decide_tool_call(request)
            result = await run_through_gate(request, handler)

        assert handler.ran is True
        assert result.content == "the tool really ran"
        publish.assert_awaited_once_with(
            record, HILApprovalStatus.APPROVED, stream_id=STREAM_ID, feedback="yes do it"
        )
        override.assert_not_awaited()  # scope "once": the user is still asked next time
        remember.assert_not_awaited()

    async def test_an_always_tool_approval_turns_off_asking_for_the_tool(self) -> None:
        handler = _Handler()
        request = make_request()
        record = make_record(status=HILApprovalStatus.APPROVED, scope="always_tool")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.get_approval", new=AsyncMock(side_effect=[None, record])),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
            patch(f"{MODULE}.publish_decision", new=AsyncMock()),
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as override,
            patch(f"{MODULE}.remember_declined_call", new=AsyncMock()) as remember,
        ):
            with pytest.raises(GraphInterrupt):
                await decide_tool_call(request)
            await run_through_gate(request, handler)

        assert handler.ran is True
        override.assert_awaited_once_with(USER_ID, "send_email", False)
        remember.assert_not_awaited()

    async def test_publish_decision_uses_the_context_stream_not_the_records(self) -> None:
        # A resumed run is on a FRESH stream; the record's stream is the closed one the
        # card was raised on. Settling the card where nobody is looking strands it.
        handler = _Handler()
        request = make_request()
        record = make_record(status=HILApprovalStatus.APPROVED, stream_id="some-other-stream")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.get_approval", new=AsyncMock(side_effect=[None, record])),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
            patch(f"{MODULE}.publish_decision", new=AsyncMock()) as publish,
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()),
            patch(f"{MODULE}.remember_declined_call", new=AsyncMock()),
        ):
            with pytest.raises(GraphInterrupt):
                await decide_tool_call(request)
            await run_through_gate(request, handler)

        assert handler.ran is True
        publish.assert_awaited_once_with(
            record, HILApprovalStatus.APPROVED, stream_id=STREAM_ID, feedback=None
        )

    async def test_a_denied_record_remembers_the_decline_and_refuses(self) -> None:
        handler = _Handler()
        request = make_request()
        record = make_record(status=HILApprovalStatus.DENIED, feedback="wrong person")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.get_approval", new=AsyncMock(side_effect=[None, record])),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
            patch(f"{MODULE}.publish_decision", new=AsyncMock()),
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()),
            patch(f"{MODULE}.remember_declined_call", new=AsyncMock()) as remember,
        ):
            with pytest.raises(GraphInterrupt):
                await decide_tool_call(request)
            result = await run_through_gate(request, handler)

        assert handler.ran is False
        assert result.additional_kwargs == {HIL_STATUS_KWARG: "denied"}
        assert result.tool_call_id == "call-1"
        assert result.name == "send_email"
        assert result.content == DENIED_TEMPLATE.format(
            tool="send_email",
            feedback=" The user said: 'wrong person'.",
            waited=approval_window_label(),
        )
        remember.assert_awaited_once_with(STREAM_ID, "send_email", {}, "wrong person")

    async def test_a_denial_without_feedback_is_not_quoted(self) -> None:
        # A silent decline must not read as if the user said something they didn't.
        handler = _Handler()
        request = make_request()
        record = make_record(status=HILApprovalStatus.DENIED, feedback=None)
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.get_approval", new=AsyncMock(side_effect=[None, record])),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
            patch(f"{MODULE}.publish_decision", new=AsyncMock()),
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()),
            patch(f"{MODULE}.remember_declined_call", new=AsyncMock()),
        ):
            with pytest.raises(GraphInterrupt):
                await decide_tool_call(request)
            result = await run_through_gate(request, handler)

        assert handler.ran is False
        assert result.content == DENIED_TEMPLATE.format(
            tool="send_email", feedback="", waited=approval_window_label()
        )

    async def test_a_timeout_record_is_not_remembered_and_reads_as_timeout(self) -> None:
        # A timeout is not a refusal — the user may just be away, so the same call may
        # legitimately be asked about again later. Remembering it would suppress that.
        handler = _Handler()
        request = make_request()
        record = make_record(status=HILApprovalStatus.TIMEOUT)
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.get_approval", new=AsyncMock(side_effect=[None, record])),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
            patch(f"{MODULE}.publish_decision", new=AsyncMock()),
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()),
            patch(f"{MODULE}.remember_declined_call", new=AsyncMock()) as remember,
        ):
            with pytest.raises(GraphInterrupt):
                await decide_tool_call(request)
            result = await run_through_gate(request, handler)

        assert handler.ran is False
        assert result.additional_kwargs == {HIL_STATUS_KWARG: "timeout"}
        assert result.tool_call_id == "call-1"
        assert result.name == "send_email"
        assert result.content == TIMEOUT_TEMPLATE.format(
            tool="send_email", feedback="", waited=approval_window_label()
        )
        remember.assert_not_awaited()

    async def test_a_still_pending_record_on_the_replay_pauses_again(self) -> None:
        # The decision has not landed; the replay must pause again, not apply a pending
        # record as if it were a decision.
        handler = _Handler()
        request = make_request()
        approval_id = approval_id_for(CONVERSATION_ID, "call-1")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(
                f"{MODULE}.get_approval",
                new=AsyncMock(side_effect=[None, make_record(status=HILApprovalStatus.PENDING)]),
            ) as get_record,
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as publish,
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
        ):
            with pytest.raises(GraphInterrupt):
                await decide_tool_call(request)
            with pytest.raises(GraphInterrupt):
                await run_through_gate(request, handler)

        assert handler.ran is False
        assert publish.await_count == 2  # asked again — the upsert stays a no-op downstream
        assert get_record.await_args_list == [call(approval_id), call(approval_id)]


class TestAutoApproval:
    """Auto mode: the intent judge runs only when no card is up and nothing pauses."""

    async def test_an_aligned_judge_clears_the_call_and_publishes_a_receipt(self) -> None:
        handler = _Handler()
        request = make_request(
            tool=make_tool(),
            messages=[
                ai_message_with_calls(
                    {"id": "prior-1", "name": "get_contacts", "args": {"query": "bob"}},
                    {"id": "call-1", "name": "send_email", "args": {"to": "bob@example.com"}},
                )
            ],
        )
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="Gmail")),
            patch(f"{MODULE}.has_pausing_sibling", new=AsyncMock(return_value=False)) as sibling,
            patch(
                f"{MODULE}.judge_intent",
                new=AsyncMock(return_value=IntentDecision(aligned=True, reason="user said send it")),
            ) as judge,
            patch(f"{MODULE}.publish_auto_approval", new=AsyncMock()) as receipt,
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as ask,
        ):
            result = await run_through_gate(request, handler)

        assert handler.ran is True
        assert result.content == "the tool really ran"
        ask.assert_not_awaited()
        receipt.assert_awaited_once_with(
            approval_id=approval_id_for(CONVERSATION_ID, "call-1"),
            stream_id=STREAM_ID,
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            tool_call=GatedCall(name="send_email", id="call-1", args={}),
            summary=build_summary("send_email", {}, "Gmail"),
            integration_name="Gmail",
            reason="user said send it",
        )
        judge.assert_awaited_once_with(
            user_id=USER_ID,
            user_messages=["send the deck to bob"],
            tool_name="send_email",
            description="Send an email.",
            args={},
            summary=build_summary("send_email", {}, "Gmail"),
            # The pending call itself is in state and must be dropped by id — only
            # actions that already happened are prior context for the judge.
            prior_calls=[PriorCall(name="get_contacts", args={"query": "bob"})],
        )
        sibling.assert_awaited_once_with(request, USER_ID, "call-1")
        assert gate_module.log.info.call_args.args[0] == "[HIL] auto-approved"
        assert gate_module.log.info.call_args.kwargs == {
            "call_name": "send_email",
            "reason": "user said send it",
        }

    async def test_a_misaligned_judge_asks_the_user(self) -> None:
        handler = _Handler()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.has_pausing_sibling", new=AsyncMock(return_value=False)),
            patch(
                f"{MODULE}.judge_intent",
                new=AsyncMock(return_value=IntentDecision(aligned=False, reason="too broad")),
            ),
            patch(f"{MODULE}.publish_auto_approval", new=AsyncMock()) as receipt,
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as ask,
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
        ):
            with pytest.raises(GraphInterrupt):
                await run_through_gate(make_request(), handler)

        assert handler.ran is False
        receipt.assert_not_awaited()
        ask.assert_awaited_once()

    async def test_a_judge_that_refuses_to_judge_asks_the_user(self) -> None:
        # ``None`` means "don't spend the judge call" — the call is asked, never run.
        handler = _Handler()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.has_pausing_sibling", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.judge_intent", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_auto_approval", new=AsyncMock()) as receipt,
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as ask,
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
        ):
            with pytest.raises(GraphInterrupt):
                await run_through_gate(make_request(), handler)

        assert handler.ran is False
        receipt.assert_not_awaited()
        ask.assert_awaited_once()

    async def test_a_card_already_up_skips_the_judge(self) -> None:
        # The user has been asked; the answer is theirs to give. Re-judging would both
        # re-run a non-deterministic LLM call on every replay and steal the question.
        handler = _Handler()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=make_record())),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.has_pausing_sibling", new=AsyncMock()) as sibling,
            patch(f"{MODULE}.judge_intent", new=AsyncMock()) as judge,
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as ask,
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
        ):
            with pytest.raises(GraphInterrupt):
                await run_through_gate(make_request(), handler)

        assert handler.ran is False
        judge.assert_not_awaited()
        sibling.assert_not_awaited()
        ask.assert_awaited_once()

    async def test_a_pausing_sibling_skips_the_judge(self) -> None:
        # The sibling's interrupt will re-run this whole node — and the judge is the one
        # thing in it that is not idempotent. Auto-approval must wait for a turn without
        # a pause in it.
        handler = _Handler()
        request = make_request()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.has_pausing_sibling", new=AsyncMock(return_value=True)) as sibling,
            patch(f"{MODULE}.judge_intent", new=AsyncMock()) as judge,
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt", side_effect=_raising_interrupt),
        ):
            with pytest.raises(GraphInterrupt):
                await run_through_gate(request, handler)

        assert handler.ran is False
        judge.assert_not_awaited()
        sibling.assert_awaited_once_with(request, USER_ID, "call-1")
        assert gate_module.log.info.call_args.args[0] == "[HIL] not auto-approving : a sibling call may pause"
        assert gate_module.log.info.call_args.kwargs == {"name": "send_email"}


class TestUnpausableRun:
    async def test_a_gated_call_in_a_background_run_is_refused(self) -> None:
        # A background/queued run has no live client to answer a card, so a gated call
        # there must be failed closed — never run unapproved, never parked on an
        # interrupt nothing can resume.
        handler = _Handler()
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "execution_mode": "background",
            }
        )
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")) as policy,
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock()),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as publish,
        ):
            result = await run_through_gate(request, handler)

        assert handler.ran is False
        assert publish.await_count == 0
        policy.assert_awaited_once_with(request, USER_ID, "send_email")
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs == {HIL_STATUS_KWARG: "denied"}
        assert result.tool_call_id == "call-1"
        assert result.name == "send_email"
        assert result.content == UNPAUSABLE_DENIAL_TEMPLATE.format(tool="send_email")
        assert gate_module.log.info.call_args.args[0] == "[HIL] Denying gated : run cannot pause for approval"
        assert gate_module.log.info.call_args.kwargs == {"name": "send_email"}


class TestIntegrationNameFor:
    """The one place the gate reads the registry itself — the tool's integration
    label that rides on the card and the summary."""

    async def test_the_integration_name_comes_from_the_tools_category(self) -> None:
        class _Registry:
            def __init__(self) -> None:
                self.category_of_called: list[str] = []
                self.category_called: list[str] = []

            def get_category_of_tool(self, tool_name: str) -> str:
                self.category_of_called.append(tool_name)
                return "composio_gmail"

            def get_category(self, name: str) -> Any:
                self.category_called.append(name)
                return (
                    SimpleNamespace(integration_name="Gmail")
                    if name == "composio_gmail"
                    else None
                )

        registry = _Registry()
        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)):
            assert await gate_module._integration_name_for("send_email") == "Gmail"
        assert registry.category_of_called == ["send_email"]
        assert registry.category_called == ["composio_gmail"]

    async def test_a_tool_without_a_category_has_no_integration_name(self) -> None:
        class _EmptyRegistry:
            def get_category_of_tool(self, tool_name: str) -> str:
                return "unknown"

            def get_category(self, name: str) -> Any:
                return None

        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_EmptyRegistry())):
            assert await gate_module._integration_name_for("send_email") is None
