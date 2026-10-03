"""A reaction the comms agent sends in place of a written acknowledgment reaches the transcript.

Comms acknowledges handed-off work with a tap-back (an emoji_ack frame) instead of a
sentence. The transport used to drop that frame, so the judge saw no reply at all
and graded "the reply is one short line" against silence.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites import quality
from scripts.evals.suites.quality import ChatStreamTransport

REACTION = "\U0001f6d2"
REACTION_FRAME = {"emoji_ack": {"emoji": REACTION, "reacts_to_message_id": "m1"}}


def test_emoji_ack_frame_becomes_the_turns_reaction() -> None:
    record = quality._parse_frames([REACTION_FRAME])

    assert record["reaction"] == REACTION
    assert record["text"] == ""


async def test_transport_writes_the_reaction_into_the_transcript() -> None:
    provider = ProviderConfig(
        name="p",
        lane="custom",
        base_url=None,
        api_key=None,
        model="m",
        budget_usd=0.0,
        price_in_per_1m=0.0,
        price_out_per_1m=0.0,
    )
    turn = {
        "conversation_id": "c1",
        "text": "",
        "tool_calls": [],
        "raw": [],
        "error": None,
        "follow_up_actions": None,
        "reaction": REACTION,
    }
    transport = ChatStreamTransport()
    with (
        patch.object(transport, "_mint_user", AsyncMock(return_value="u@gaia.local")),
        patch.object(transport, "_stream_turn", AsyncMock(return_value=turn)),
    ):
        run = await transport.run(
            Case(id="react", ticket="t", prompt="add milk to my list"),
            EvalConfig(providers={}, rotation_order=[], default_max_usd=0.0, judge={}),
            EvalCostTracker({"p": provider}, 1.0),
            provider,
        )

    assert run.messages[-1] == {
        "role": "assistant",
        "content": f"[reaction: {REACTION}]",
        "kind": quality.REACTION_KIND,
    }


def test_emoji_gate_allows_a_reaction_but_not_an_emoji_in_text() -> None:
    reacted = CaseRun(
        case_id="react",
        messages=[
            {"role": "user", "content": "add milk to my list"},
            {"role": "assistant", "content": f"[reaction: {REACTION}]", "kind": "reaction"},
        ],
    )
    typed = CaseRun(
        case_id="react",
        messages=[
            {"role": "user", "content": "add milk to my list"},
            {"role": "assistant", "content": f"adding it {REACTION}"},
        ],
    )

    assert quality._emoji_discipline_check(reacted)[0] == 1.0
    assert quality._emoji_discipline_check(typed)[0] == 0.0
