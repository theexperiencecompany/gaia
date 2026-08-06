"""Whole-journey attacks on the gate (app/services/hil/gate.py).

The existing gate tests attack its *edges* — malformed resume payloads, missing identity,
broken dependencies. This file attacks the **journeys**: ask → approve → the tool runs,
ask → deny → it never does, expiry → the model is told it expired, auto → receipt → run.

Each drives the real ``decide_tool_call``, so the assertions are about the seam between its
steps rather than any one of them: does an approval actually reach the handler, does a
denial actually stop it, does an expiry produce a *different* message from a refusal, and
does the receipt land before the action rather than after it.

Mocked: the store, the publish/notify side, the intent judge, and ``interrupt()`` — the
I/O edges. The orchestration between them is the production code under test.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
import pytest

from app.constants.hil import HIL_STATUS_KWARG
from app.models.hil_models import HILApprovalStatus
from app.services.hil.intent import IntentDecision
from app.services.hil.utils import approval_window_label

from .conftest import make_record, make_request, run_through_gate

MODULE = "app.services.hil.gate"


class Handler:
    """Stands in for the real tool, and records WHEN it ran relative to the gate's own
    side effects — the receipt-before-action ordering is a requirement, not an accident."""

    def __init__(self, log: list[str], explode: bool = False) -> None:
        self.log = log
        self.explode = explode
        self.runs = 0

    async def __call__(self, request: Any) -> ToolMessage:
        self.runs += 1
        self.log.append("handler")
        if self.explode:
            raise RuntimeError("the tool itself blew up")
        return ToolMessage(content="the tool really ran", tool_call_id="call-1")


@pytest.fixture
def gate():
    """Every I/O edge of the gate, with the journey-neutral defaults: no prior record, no
    earlier decline, no integration lookup."""
    log: list[str] = []
    with (
        patch(f"{MODULE}.log"),
        patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=None)) as approval,
        patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
        patch(f"{MODULE}.remember_declined_call", new=AsyncMock()) as remember,
        patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
        patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as override,
        patch(f"{MODULE}.publish_decision", new=AsyncMock()) as outcome,
        patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")) as policy,
        patch(f"{MODULE}.judge_intent", new=AsyncMock()) as judge,
        patch(f"{MODULE}.has_pausing_sibling", new=AsyncMock(return_value=False)),
        # Raises, exactly as LangGraph's does: it is control flow that EXITS the run,
        # not a call that returns a decision. A mock that returned one would let
        # ``settle_message_approvals`` spin forever on a still-pending approval.
        patch(f"{MODULE}.interrupt", side_effect=GraphInterrupt(())) as interrupt,
        patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as request_card,
        patch(f"{MODULE}.publish_auto_approval", new=AsyncMock()) as receipt,
    ):

        async def _record_card(**kwargs: Any) -> None:
            log.append("card")

        async def _record_receipt(**kwargs: Any) -> None:
            log.append("receipt")

        request_card.side_effect = _record_card
        receipt.side_effect = _record_receipt
        yield {
            "log": log,
            "approval": approval,
            "policy": policy,
            "judge": judge,
            "interrupt": interrupt,
            "card": request_card,
            "receipt": receipt,
            "outcome": outcome,
            "remember": remember,
            "override": override,
        }


async def asks(gate: dict, request: Any) -> None:
    """Pass one: the card goes up and the run parks on ``interrupt()``.

    Every journey below starts here, because that is the only place a card is ever
    published. Skipping it would let a test assert an approval the user was never shown.
    ``interrupt`` is patched to RAISE, exactly as LangGraph's does — it is control flow
    that exits the run, not a call that returns a decision.
    """
    del gate
    with pytest.raises(GraphInterrupt):
        await run_through_gate(request, Handler([]))


def decides(gate: dict, *, status: str, scope: str = "once", feedback: str | None = None) -> None:
    """The user's decision, as the gate reads it: a SETTLED RECORD.

    Never a resume payload. ``resolve_approval`` writes the decision to Mongo and the
    ``Command(resume=...)`` that follows is only a wake-up whose value is ignored — so a
    test that fed a payload would be exercising a path production no longer has.
    """
    gate["approval"].return_value = make_record(
        status=HILApprovalStatus(status), scope=scope, feedback=feedback
    )


def status_of(result: ToolMessage) -> str:
    return result.additional_kwargs[HIL_STATUS_KWARG]


class TestApproveJourney:
    async def test_an_approval_actually_reaches_the_tool(self, gate: dict) -> None:
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="approved", scope="once")

        result = await run_through_gate(make_request(), handler)

        assert handler.runs == 1
        assert result.content == "the tool really ran"
        assert gate["log"] == ["card", "handler"]

    async def test_the_card_is_published_before_the_pause_not_after(self, gate: dict) -> None:
        # The pause checkpoints and EXITS the process. Anything published after
        # interrupt() on the first pass never runs, so the user would be asked to approve
        # something they can never see.
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="approved")

        await run_through_gate(make_request(), handler)

        gate["card"].assert_awaited_once()
        assert gate["log"].index("card") < gate["log"].index("handler")

    async def test_always_allow_this_tool_writes_the_override(self, gate: dict) -> None:
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="approved", scope="always_tool")

        await run_through_gate(make_request(), handler)

        assert handler.runs == 1
        gate["override"].assert_awaited_once()
        args = gate["override"].await_args.args
        assert args[1] == "send_email"
        assert args[2] is False, "always_tool must record 'never ask', not 'always ask'"

    async def test_a_one_off_approval_changes_no_preference(self, gate: dict) -> None:
        # Approving once must not silently disarm the gate for every future call.
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="approved", scope="once")

        await run_through_gate(make_request(), handler)

        gate["override"].assert_not_awaited()

    async def test_an_approval_is_not_remembered_as_a_decline(self, gate: dict) -> None:
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="approved")

        await run_through_gate(make_request(), handler)

        gate["remember"].assert_not_awaited()


class TestDenyJourney:
    async def test_a_denial_stops_the_tool_and_says_so(self, gate: dict) -> None:
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="denied", feedback="wrong recipient")

        result = await run_through_gate(make_request(), handler)

        assert handler.runs == 0
        assert status_of(result) == "denied"
        assert "wrong recipient" in result.content, (
            "the user's correction must reach the model, or a decline is a dead end"
        )

    async def test_a_bare_decline_still_forbids_routing_around_the_gate(self, gate: dict) -> None:
        # With no feedback, "adjust your approach" reads as "find another way" — the one
        # thing a decline must not license. The refusal has to say so explicitly.
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="denied", feedback=None)

        result = await run_through_gate(make_request(), handler)

        assert handler.runs == 0
        assert "another tool" in result.content

    async def test_a_denial_is_remembered_so_a_retry_is_not_re_asked(self, gate: dict) -> None:
        # The executor never learns its subagent was declined, so it retries. Re-prompting
        # the user for the same call is the loop this kills.
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="denied", feedback="no")

        await run_through_gate(make_request(), handler)

        gate["remember"].assert_awaited_once()
        args = gate["remember"].await_args.args
        assert args[1] == "send_email"
        assert args[3] == "no", "the original feedback must ride along with the memory"


class TestExpiryJourney:
    async def test_an_expired_request_reads_as_expired_not_as_a_refusal(self, gate: dict) -> None:
        # A timeout is not a decision. Telling the model "the user declined" would make it
        # report a refusal the user never made.
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="timeout")

        result = await run_through_gate(make_request(), handler)

        assert handler.runs == 0
        assert status_of(result) == "timeout"
        assert "expired" in result.content

    async def test_the_model_is_told_how_long_it_waited(self, gate: dict) -> None:
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="timeout")

        result = await run_through_gate(make_request(), handler)

        assert approval_window_label() in result.content

    async def test_an_expiry_is_never_remembered_as_a_decline(self, gate: dict) -> None:
        # THE distinction: the user was away, not opposed. Remembering it would auto-deny
        # every later retry in the turn without ever asking them again.
        handler = Handler(gate["log"])
        await asks(gate, make_request())
        decides(gate, status="timeout")

        await run_through_gate(make_request(), handler)

        gate["remember"].assert_not_awaited()


class TestApprovalWindowLabel:
    """The wording the expiry message carries. Pure arithmetic, so the boundaries are
    where it breaks."""

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (6 * 3600, "6 hours"),
            (3600, "1 hour"),
            (2 * 3600, "2 hours"),
            (1800, "30 minutes"),
            (60, "1 minute"),
            (90, "1 minute"),
            (30, "1 minute"),  # sub-minute must never render as "0 minutes"
            (0, "1 minute"),
        ],
    )
    def test_renders_a_human_window(self, seconds: int, expected: str) -> None:
        with patch("app.services.hil.utils.HIL_APPROVAL_TIMEOUT_SECONDS", seconds):
            assert approval_window_label() == expected

    def test_an_hour_boundary_does_not_render_as_minutes(self) -> None:
        with patch("app.services.hil.utils.HIL_APPROVAL_TIMEOUT_SECONDS", 3660):
            assert approval_window_label() == "1 hour"


class TestAutoJourney:
    async def test_an_authorized_call_runs_without_ever_asking(self, gate: dict) -> None:
        gate["policy"].return_value = "auto"
        gate["judge"].return_value = IntentDecision(True, "you said send the deck to bob")
        handler = Handler(gate["log"])

        result = await run_through_gate(make_request(), handler)

        assert handler.runs == 1
        assert result.content == "the tool really ran"
        gate["interrupt"].assert_not_called()
        gate["card"].assert_not_awaited()

    async def test_the_receipt_is_recorded_before_the_action_not_after(self, gate: dict) -> None:
        # If the tool then fails, the user must still see that GAIA decided to act, and
        # why. Publishing after the handler loses exactly the case that needs explaining.
        gate["policy"].return_value = "auto"
        gate["judge"].return_value = IntentDecision(True, "you said send the deck to bob")
        handler = Handler(gate["log"], explode=True)

        with pytest.raises(RuntimeError):
            await run_through_gate(make_request(), handler)

        gate["receipt"].assert_awaited_once()
        assert gate["log"] == ["receipt", "handler"]

    async def test_the_judges_reason_travels_onto_the_receipt(self, gate: dict) -> None:
        # A receipt with no "why" is not accountability.
        gate["policy"].return_value = "auto"
        gate["judge"].return_value = IntentDecision(True, "you said send the deck to bob")

        await run_through_gate(make_request(), Handler(gate["log"]))

        assert gate["receipt"].await_args.kwargs["reason"] == "you said send the deck to bob"

    async def test_an_unauthorized_call_falls_back_to_asking(self, gate: dict) -> None:
        gate["policy"].return_value = "auto"
        gate["judge"].return_value = IntentDecision(False, "you never asked for this")
        await asks(gate, make_request())
        decides(gate, status="approved")
        handler = Handler(gate["log"])

        await run_through_gate(make_request(), handler)

        gate["receipt"].assert_not_awaited()
        gate["card"].assert_awaited_once()
        gate["interrupt"].assert_called_once()

    async def test_ask_mode_never_consults_the_judge(self, gate: dict) -> None:
        # The judge is an LLM call on the tool-call hot path. In always_ask it decides
        # nothing, so paying for it would be pure latency.
        gate["policy"].return_value = "ask"
        await asks(gate, make_request())
        decides(gate, status="approved")

        await run_through_gate(make_request(), Handler(gate["log"]))

        gate["judge"].assert_not_awaited()


class TestUnpausableRun:
    """A background/queued run carries an identity but has no live client to answer. The
    gated call must be refused — never run unapproved, never parked on an interrupt that
    nothing can resume."""

    def background_request(self) -> Any:
        return make_request(
            configurable={
                "stream_id": "stream-1",
                "user_id": "507f1f77bcf86cd799439011",
                "conversation_id": "conv-1",
                "execution_mode": "background",
                "user_messages": ["send the deck to bob"],
            }
        )

    async def test_a_gated_call_is_refused_rather_than_run(self, gate: dict) -> None:
        handler = Handler(gate["log"])

        result = await run_through_gate(self.background_request(), handler)

        assert handler.runs == 0
        assert status_of(result) == "denied"

    async def test_nobody_is_asked_and_nothing_is_parked(self, gate: dict) -> None:
        # Publishing a card to a user who cannot answer it, or pausing a run nothing can
        # resume, are the two ways this could fail while still refusing the call.
        await run_through_gate(self.background_request(), Handler(gate["log"]))

        gate["card"].assert_not_awaited()
        gate["interrupt"].assert_not_called()

    async def test_an_ungated_call_still_runs_in_a_background_run(self, gate: dict) -> None:
        # Failing closed must apply to the gated set only — a background run is otherwise
        # a normal run, and gating everything would break every workflow and cron task.
        gate["policy"].return_value = "allow"
        handler = Handler(gate["log"])

        result = await run_through_gate(self.background_request(), handler)

        assert handler.runs == 1
        assert result.content == "the tool really ran"
