"""Auto mode v2 outcomes (app/services/hil/intent.py).

The judge returns accept or ask, never a refusal: a call auto mode doubts goes
to the user as a card. Tests here pin the outcome vocabulary.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware.types import ToolCallRequest
import pytest

from app.constants.hil import AUTO_ASK_NOTE, HIL_STATUS_KWARG, JevChoice
from app.models.hil_models import HILPreferences
from app.services.hil import gate, intent
from app.services.hil.intent import (
    AutoContext,
    AutoHistory,
    IntentDecision,
    IntentJudge,
    JudgedCall,
    judge_intent,
)
from app.services.hil.jev_judge import JevVerdict
from app.services.hil.utils import PriorCall, unpack_tool_call

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID, make_request, make_tool

MODULE = "app.services.hil.intent"


@pytest.fixture(autouse=True)
def _no_saved_instructions() -> Iterator[None]:
    """Give these users no saved instructions for the gate to read."""
    with patch.object(gate, "get_all_instructions", new=AsyncMock(return_value={})):
        yield


class FakeJudge(IntentJudge):
    """A future JEV-backed judge stands here: same Protocol, no LLM."""

    def __init__(self, decision: IntentDecision) -> None:
        self._decision = decision
        self.calls = 0
        self.assistants: list[intent.AssistantTurns] = []
        self.autos: list[AutoContext] = []

    async def decide(
        self,
        *,
        auto: AutoContext,
        user_messages: list[str],
        call: JudgedCall,
        prior_calls: list[PriorCall],
        assistant: intent.AssistantTurns = intent.AssistantTurns(),
    ) -> IntentDecision:
        self.calls += 1
        self.assistants.append(assistant)
        self.autos.append(auto)
        return self._decision


def _call() -> JudgedCall:
    return JudgedCall(
        tool_name="send_email",
        description="Send an email.",
        args={"to": "bob@example.com"},
        summary="Send email — to: bob@example.com",
    )


async def test_injected_judge_decides_without_calling_the_llm() -> None:
    fake = FakeJudge(IntentDecision(outcome="ask", reason="nope"))
    d = await judge_intent(
        AutoContext(user_id="u"),
        user_messages=["please send the deck to bob now"],
        call=_call(),
        prior_calls=[],
        judge=fake,
    )
    assert d.outcome == "ask"
    assert fake.calls == 1


async def test_the_judge_is_given_what_the_user_was_shown_and_the_runs_own_words() -> None:
    fake = FakeJudge(IntentDecision(outcome="accept", reason="asked"))
    assistant = intent.AssistantTurns(shown=("Drafted the reply to Bob.",), run=("Sending now.",))

    await judge_intent(
        AutoContext(user_id="u"),
        user_messages=["send it"],
        call=_call(),
        prior_calls=[],
        judge=fake,
        assistant=assistant,
    )

    assert fake.assistants == [assistant]


async def test_never_auto_tool_asks_without_calling_the_llm() -> None:
    # A user deny-rule: the judge declines to judge, so the call gets a card.
    fake = FakeJudge(IntentDecision(outcome="accept", reason="asked"))
    d = await judge_intent(
        AutoContext(user_id="u", never_auto=True),
        user_messages=["please send the deck to bob now"],
        call=_call(),
        prior_calls=[],
        judge=fake,
    )
    assert d.outcome == "ask"
    assert "send_email" in d.reason
    assert fake.calls == 0


async def test_the_judge_is_handed_the_users_saved_instructions_and_history() -> None:
    """The judge itself weighs saved instructions (one question, one request): judge_intent only passes them."""
    fake = FakeJudge(IntentDecision(outcome="accept", reason="asked"))
    auto = AutoContext(
        user_id="u",
        history=AutoHistory(approved_recent=2),
        standing_rules=("Always ask me before emailing my boss.",),
    )

    d = await judge_intent(
        auto,
        user_messages=["send the deck to bob"],
        call=_call(),
        prior_calls=[],
        judge=fake,
    )

    assert d.outcome == "accept"
    assert fake.autos == [auto]


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
        await gate._judge(request, context, unpack_tool_call(request), "s")
    assert judge.await_args.args[0].never_auto is True


async def _never_auto_for(request: ToolCallRequest, never_auto_tools: list[str]) -> bool:
    context = gate.read_gate_context(request)
    assert context is not None
    with (
        patch.object(
            gate,
            "get_hil_preferences",
            new=AsyncMock(
                return_value=HILPreferences(mode="auto", never_auto_tools=never_auto_tools)
            ),
        ),
        patch.object(
            gate,
            "judge_intent",
            new=AsyncMock(return_value=IntentDecision(outcome="ask", reason="x")),
        ) as judge,
    ):
        await gate._judge(request, context, unpack_tool_call(request), "s")
    return bool(judge.await_args.args[0].never_auto)


def _mcp_request(integration_id: str) -> ToolCallRequest:
    tool = make_tool(
        name="posthog_delete_item",
        metadata={"integration_id": integration_id, "mcp_server_name": "delete_item"},
    )
    return make_request(name="posthog_delete_item", tool=tool)


async def test_other_tools_ignore_the_never_auto_list() -> None:
    assert await _never_auto_for(make_request(tool=make_tool()), ["wipe_database"]) is False


async def test_never_auto_on_an_mcp_tool_is_keyed_by_its_server() -> None:
    listed = ["mcp:srv_a:delete_item"]
    assert await _never_auto_for(_mcp_request("srv_a"), listed) is True
    assert await _never_auto_for(_mcp_request("srv_b"), listed) is False


async def test_a_bare_never_auto_name_does_not_reach_an_mcp_tool_of_that_name() -> None:
    assert await _never_auto_for(_mcp_request("srv_a"), ["delete_item"]) is False


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
    ledger.find_amended = AsyncMock(return_value=None)
    ledger.register = AsyncMock(return_value="ap_abc1234567")
    return ledger


async def test_a_forbidden_verdict_asks_the_user_instead_of_refusing() -> None:
    # Auto mode never refuses on its own: a forbidden JEV verdict is a card with a plain note.
    ledger = _auto_ledger()
    verdict = JevVerdict(
        choice=JevChoice.FORBIDDEN,
        confidence=0.95,
        probabilities={JevChoice.FORBIDDEN: 0.95},
        contained=0.0,
        objection=0.0,
    )
    jev = AsyncMock(return_value=(verdict, 0, 0))
    with (
        patch("app.services.hil.gate.resolve_policy", new=AsyncMock(return_value="auto")),
        patch("app.services.hil.gate.approval_ledger_repository", new=ledger),
        patch(
            "app.services.hil.gate._integration_name_for",
            new=AsyncMock(return_value="gmail"),
        ),
        patch("app.services.hil.gate._auto_history", new=AsyncMock(return_value=AutoHistory())),
        patch(
            "app.services.hil.gate.get_hil_preferences",
            new=AsyncMock(return_value=HILPreferences()),
        ),
        patch("app.services.hil.gate.gated_tool_object", new=AsyncMock(return_value=None)),
        patch("app.services.hil.jev_judge.ask_jev", new=jev),
        patch("app.services.hil.gate.announce_approval", new=AsyncMock()),
        patch("app.services.hil.gate.asks_every_time", new=MagicMock(return_value=False)),
        patch("app.services.hil.gate.record_approval_requested", new=AsyncMock()) as requested,
    ):
        result = await gate.decide_tool_call(_auto_request())

    assert result is not None
    assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"
    ledger.register.assert_awaited_once()
    assert requested.await_args.args[2].auto_reason == AUTO_ASK_NOTE


async def test_a_throwing_judge_fails_closed_to_ask() -> None:
    # The bottom of the cascade: JEV mapping code, the LLM fallback, anything —
    # an exception out of ANY judge is a card, never a run and never a crash.

    class _Boom:
        async def decide(self, **kwargs: Any) -> IntentDecision:
            raise RuntimeError("judge exploded")

    with patch("app.services.hil.intent.log") as log:
        d = await judge_intent(
            AutoContext(user_id="u"),
            user_messages=["please send the deck to bob now"],
            call=_call(),
            prior_calls=[],
            judge=_Boom(),
        )
    assert d.outcome == "ask"
    log.error.assert_called_once_with(
        "[HIL] intent judge failed; asking",
        tool_name=_call().tool_name,
        error="judge exploded",
        error_type="RuntimeError",
    )


async def test_ask_carries_auto_mode_reason_to_card_and_model() -> None:
    # The ask contract: the card says in plain words why GAIA asks; the PENDING text
    # gives the model the judge's own reason.
    ledger = _auto_ledger()
    with (
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
        patch("app.services.hil.gate.announce_approval", new=AsyncMock()),
        patch("app.services.hil.gate.asks_every_time", new=MagicMock(return_value=False)),
        patch("app.services.hil.gate.record_approval_requested", new=AsyncMock()) as requested,
    ):
        result = await gate.decide_tool_call(_auto_request())

    assert result is not None
    assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"
    assert "Auto mode wasn't sure: vague scope" in result.content
    assert requested.await_args.args[2].auto_reason == AUTO_ASK_NOTE
