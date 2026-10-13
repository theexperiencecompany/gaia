"""Auto mode v2 outcomes (app/services/hil/intent.py).

The judge returns accept / reject / ask — never a bare boolean — so the gate
can refuse with a reason (no card) distinctly from asking (card). Tests here
pin the outcome vocabulary; the adversarial LLM-judge tests live in
test_hil_intent.py.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware.types import ToolCallRequest

from app.constants.hil import HIL_STATUS_KWARG
from app.models.hil_models import HILApprovalStatus, HILPreferences
from app.services.hil import gate
from app.services.hil.bridge import ApprovalOutcome
from app.services.hil.intent import (
    AutoContext,
    AutoHistory,
    IntentDecision,
    IntentJudge,
    JudgedCall,
    _Verdict,
    judge_intent,
)
from app.services.hil.utils import PriorCall

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID, make_request, make_tool

MODULE = "app.services.hil.intent"


class FakeJudge(IntentJudge):
    """A future JEV-backed judge stands here: same Protocol, no LLM."""

    def __init__(self, decision: IntentDecision) -> None:
        self._decision = decision
        self.calls = 0

    async def decide(
        self,
        *,
        user_id: str,
        user_messages: list[str],
        call: JudgedCall,
        prior_calls: list[PriorCall],
        history: AutoHistory,
        assistant_turns: list[str] | None = None,
    ) -> IntentDecision:
        self.calls += 1
        return self._decision


def _call() -> JudgedCall:
    return JudgedCall(
        tool_name="send_email",
        description="Send an email.",
        args={"to": "bob@example.com"},
        summary="Send email — to: bob@example.com",
    )


async def test_injected_judge_decides_without_calling_the_llm() -> None:
    fake = FakeJudge(IntentDecision(outcome="reject", reason="nope"))
    with patch(f"{MODULE}.ainvoke_structured", new=AsyncMock()) as llm:
        d = await judge_intent(
            AutoContext(user_id="u"),
            user_messages=["please send the deck to bob now"],
            call=_call(),
            prior_calls=[],
            judge=fake,
        )
    assert d.outcome == "reject"
    assert llm.await_count == 0
    assert fake.calls == 1


async def test_never_auto_tool_asks_without_calling_the_llm() -> None:
    # A user deny-rule: the judge declines to judge, so the call gets a card.
    with patch(f"{MODULE}.ainvoke_structured", new=AsyncMock()) as llm:
        d = await judge_intent(
            AutoContext(user_id="u", never_auto_tools=frozenset({"send_email"})),
            user_messages=["please send the deck to bob now"],
            call=_call(),
            prior_calls=[],
        )
    assert d.outcome == "ask"
    assert "send_email" in d.reason
    assert llm.await_count == 0


async def test_other_tools_ignore_the_never_auto_list() -> None:
    llm_verdict = _Verdict(
        authorized_scope="email bob",
        authorizing_quote="please send the deck to bob now",
        action_effect="sends an email",
        scope_gap="",
        risk_factors=[],
        injected_instructions=False,
        verdict="allow",
        reason="You asked for it.",
    )
    with patch(f"{MODULE}.ainvoke_structured", new=AsyncMock(return_value=llm_verdict)):
        d = await judge_intent(
            AutoContext(user_id="u", never_auto_tools=frozenset({"wipe_database"})),
            user_messages=["please send the deck to bob now"],
            call=_call(),
            prior_calls=[],
        )
    assert d.outcome == "accept"


async def test_gate_threads_never_auto_prefs_into_the_judge() -> None:
    request = make_request(
        tool=make_tool(),
        configurable={
            "stream_id": STREAM_ID,
            "user_id": USER_ID,
            "conversation_id": CONVERSATION_ID,
            "user_messages": ["send the deck to bob"],
        },
    )
    context = gate.read_gate_context(request)
    assert context is not None
    with (
        patch.object(
            gate,
            "get_hil_preferences",
            new=AsyncMock(
                return_value=HILPreferences(mode="auto", never_auto_tools=["send_email"])
            ),
        ),
        patch.object(
            gate,
            "judge_intent",
            new=AsyncMock(return_value=IntentDecision(outcome="ask", reason="x")),
        ) as judge,
    ):
        await gate._judge(request, context, gate.unpack_tool_call(request), None, "s")
    assert judge.await_args.args[0].never_auto_tools == frozenset({"send_email"})


async def test_unreadable_prefs_do_not_take_the_judge_down() -> None:
    # Prefs were already read for policy; a blip here skips the rule, not the call.
    request = make_request(tool=make_tool())
    context = gate.read_gate_context(request)
    assert context is not None
    with (
        patch.object(gate, "get_hil_preferences", new=AsyncMock(side_effect=RuntimeError("down"))),
        patch.object(
            gate,
            "judge_intent",
            new=AsyncMock(return_value=IntentDecision(outcome="ask", reason="x")),
        ) as judge,
    ):
        await gate._judge(request, context, gate.unpack_tool_call(request), None, "s")
    assert judge.await_args.args[0].never_auto_tools == frozenset()


def _auto_request() -> ToolCallRequest:
    return make_request(
        name="GMAIL_SEND_EMAIL",
        args={"to": "b@x"},
        configurable={
            "stream_id": STREAM_ID,
            "user_id": USER_ID,
            "conversation_id": CONVERSATION_ID,
            "user_messages": ["send it"],
        },
    )


def _auto_ledger() -> MagicMock:
    ledger = MagicMock()
    ledger.find_live = AsyncMock(return_value=None)
    ledger.find_latest_denied = AsyncMock(return_value=None)
    ledger.register = AsyncMock(return_value="ap_abc1234567")
    return ledger


async def test_auto_reject_registers_no_card_and_arms_decline_memory() -> None:
    # A refusal is not a question: no row, no card — but the retry must refuse
    # without spending another judge call.
    ledger = _auto_ledger()
    with (
        patch("app.services.hil.gate.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
        patch("app.services.hil.gate.resolve_policy", new=AsyncMock(return_value="auto")),
        patch("app.services.hil.gate.approval_ledger_repository", new=ledger),
        patch(
            "app.services.hil.gate._integration_name_for",
            new=AsyncMock(return_value="gmail"),
        ),
        patch(
            "app.services.hil.gate._judge",
            new=AsyncMock(return_value=IntentDecision(outcome="reject", reason="stop spamming")),
        ),
        patch("app.services.hil.gate.publish_ledger_request", new=AsyncMock()) as pub,
        patch("app.services.hil.gate.remember_declined_call", new=AsyncMock()) as remember,
        patch("app.services.hil.gate.interrupt") as intr,
    ):
        result = await gate.decide_tool_call(_auto_request())

    assert result is not None
    assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"
    assert "Auto-approve declined" in result.content
    assert "stop spamming" in result.content
    ledger.register.assert_not_awaited()
    pub.assert_not_awaited()
    intr.assert_not_called()
    remember.assert_awaited_once_with(
        "stream-1", "GMAIL_SEND_EMAIL", {"to": "b@x"}, "stop spamming", auto=True
    )


async def test_a_throwing_judge_fails_closed_to_ask() -> None:
    # The bottom of the cascade: JEV mapping code, the LLM fallback, anything —
    # an exception out of ANY judge is a card, never a run and never a crash.

    class _Boom:
        async def decide(self, **kwargs: Any) -> IntentDecision:
            raise RuntimeError("judge exploded")

    with patch(f"{MODULE}.ainvoke_structured", new=AsyncMock()) as llm:
        d = await judge_intent(
            AutoContext(user_id="u"),
            user_messages=["please send the deck to bob now"],
            call=_call(),
            prior_calls=[],
            judge=_Boom(),
        )
    assert d.outcome == "ask"
    assert llm.await_count == 0


async def test_ask_carries_auto_mode_reason_to_card_and_model() -> None:
    # The ask contract: same async flow, but the card and the PENDING text say
    # auto mode was unsure and why — never a bare "needs your decision".
    ledger = _auto_ledger()
    with (
        patch("app.services.hil.gate.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
        patch("app.services.hil.gate.resolve_policy", new=AsyncMock(return_value="auto")),
        patch("app.services.hil.gate.approval_ledger_repository", new=ledger),
        patch(
            "app.services.hil.gate._integration_name_for",
            new=AsyncMock(return_value="gmail"),
        ),
        patch(
            "app.services.hil.gate._judge",
            new=AsyncMock(return_value=IntentDecision(outcome="ask", reason="vague scope")),
        ),
        patch("app.services.hil.gate.publish_ledger_request", new=AsyncMock()) as pub,
        patch("app.services.hil.gate.interrupt") as intr,
    ):
        result = await gate.decide_tool_call(_auto_request())

    assert result is not None
    assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"
    assert "Auto mode wasn't sure: vague scope" in result.content
    assert pub.await_args.kwargs["auto_reason"] == "Auto mode wasn't sure: vague scope"
    intr.assert_not_called()


async def test_remembered_auto_reject_refuses_a_retry_without_rejudge_or_card() -> None:
    ledger = _auto_ledger()
    declined = ApprovalOutcome(status=HILApprovalStatus.DENIED, feedback="stop spamming", auto=True)
    with (
        patch("app.services.hil.gate.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
        patch("app.services.hil.gate.resolve_policy", new=AsyncMock(return_value="auto")),
        patch("app.services.hil.gate.approval_ledger_repository", new=ledger),
        patch(
            "app.services.hil.gate.recall_declined_call",
            new=AsyncMock(return_value=declined),
        ),
        patch("app.services.hil.gate._judge", new=AsyncMock()) as judge,
        patch("app.services.hil.gate.publish_ledger_request", new=AsyncMock()) as pub,
        patch("app.services.hil.gate.interrupt") as intr,
    ):
        result = await gate.decide_tool_call(_auto_request())

    assert result is not None
    assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"
    # The user was never asked — the retry must not claim they declined.
    assert "Auto-approve declined" in result.content
    assert "The user declined" not in result.content
    judge.assert_not_awaited()
    ledger.register.assert_not_awaited()
    pub.assert_not_awaited()
    intr.assert_not_called()
