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
from app.services.hil.bridge import ApprovalOutcome
from app.services.hil.gate import _outcome_from_resume, gate_tool_call, read_gate_context

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID, make_request

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


class TestResumePayload:
    """``interrupt()`` hands back whatever resumed the thread. An approval must never be
    inferred from a payload the gate does not fully recognise."""

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            "approved",  # a bare string, not the dict the gate expects
            {},  # no status at all
            {"status": "pending"},  # not a terminal decision
            {"status": "auto_approved"},  # a record status, not a resumable one
            {"status": "abandoned"},  # resolution.py maps this to denied before sending
            {"status": "APPROVED"},  # case must not be coerced
            {"status": True},
            {"approved": True},  # attacker-shaped payload
        ],
    )
    def test_anything_unrecognised_is_a_denial(self, payload: Any) -> None:
        assert _outcome_from_resume(payload).status == "denied"

    def test_a_real_approval_is_honoured(self) -> None:
        # The positive control: if this fails, nothing can ever be approved.
        outcome = _outcome_from_resume({"status": "approved", "feedback": None, "scope": "once"})
        assert outcome.status == "approved"

    def test_scope_defaults_to_once_when_absent(self) -> None:
        # A missing scope must not become "always_tool" — that would permanently ungate
        # the tool off the back of a single click.
        assert _outcome_from_resume({"status": "approved"}).scope == "once"

    def test_denial_feedback_is_carried_back_to_the_model(self) -> None:
        outcome = _outcome_from_resume({"status": "denied", "feedback": "wrong recipient"})
        assert outcome.status == "denied"
        assert outcome.feedback == "wrong recipient"


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
            result = await gate_tool_call(make_request(), handler)

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
            result = await gate_tool_call(make_request(), handler)

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
            await gate_tool_call(make_request(), handler)

        assert handler.ran is False

    async def test_a_tools_own_failure_is_not_converted_into_a_gate_denial(self) -> None:
        # The tool ran and blew up. That is a tool error, and the model must see it as
        # one — not as "the gate denied you", which would send the agent down the wrong
        # recovery path.
        async def exploding_handler(_: Any) -> ToolMessage:
            raise ValueError("the API rejected the request")

        with patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="allow")):
            with pytest.raises(ValueError, match="the API rejected the request"):
                await gate_tool_call(make_request(), exploding_handler)


class TestGateBypasses:
    async def test_an_exempt_tool_runs_without_any_gate_check(self) -> None:
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock()) as policy:
            result = await gate_tool_call(make_request(name="call_executor"), handler)

        assert handler.ran is True
        assert result.content == "the tool really ran"
        assert policy.await_count == 0

    async def test_an_ungateable_run_executes_the_tool(self) -> None:
        # A background/queued run has nobody to ask. It runs — by design.
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock()) as policy:
            await gate_tool_call(make_request(configurable={}), handler)

        assert handler.ran is True
        assert policy.await_count == 0

    async def test_an_allowed_policy_runs_the_tool(self) -> None:
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="allow")):
            await gate_tool_call(make_request(), handler)
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
            result = await gate_tool_call(make_request(), handler)

        assert handler.ran is False
        assert publish.await_count == 0  # the user is NOT asked a second time
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"
        assert "wrong person" in result.content
