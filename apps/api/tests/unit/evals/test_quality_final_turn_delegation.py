"""A session case can gate on whether its LAST turn handed work off.

Regression cover for a run-wide count that could not see the bug it was written
for: the user unblocks a task ("ok reconnected posthog") and the agent replies
"perfect, now I can do that" without resuming it. Turn 1 had already called
call_executor, so a gate over every turn's calls passed that reply.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.scorers import EXECUTOR_HANDOFF_TOOL
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites import quality
from scripts.evals.suites.quality import QUALITY_GATES, ChatStreamTransport

HANDOFF: dict[str, object] = {
    "name": EXECUTOR_HANDOFF_TOOL,
    "args": {"task": "Pull the user's PostHog dashboards"},
}
TURNS = ["pull up my posthog dashboards", "ok reconnected posthog"]


def _case() -> Case:
    return Case(
        id="final-turn",
        ticket="t",
        prompt=TURNS[0],
        expected={"delegation": "required"},
        setup={"turns": TURNS},
    )


def _run(final_turn_tool_calls: list[dict[str, object]]) -> CaseRun:
    return CaseRun(
        case_id="final-turn",
        messages=[
            {"role": "user", "content": TURNS[0]},
            {"role": "assistant", "content": "getting you a PostHog link"},
            {"role": "user", "content": TURNS[1]},
            {"role": "assistant", "content": "perfect, now I can pull those up"},
        ],
        tool_calls=[HANDOFF, *final_turn_tool_calls],
        final_turn_tool_calls=final_turn_tool_calls,
        text="perfect, now I can pull those up",
    )


@pytest.mark.regression
def test_an_earlier_handoff_does_not_satisfy_the_final_turn() -> None:
    assert QUALITY_GATES["final_turn_delegation"](_case(), _run([])) == 0.0


@pytest.mark.regression
def test_a_final_turn_handoff_passes() -> None:
    assert QUALITY_GATES["final_turn_delegation"](_case(), _run([HANDOFF])) == 1.0


@pytest.mark.regression
async def test_transport_records_only_the_last_turns_calls() -> None:
    turn_one = {"conversation_id": "c1", "text": "getting you a link", "tool_calls": [HANDOFF]}
    turn_two = {"conversation_id": "c1", "text": "now I can do that", "tool_calls": []}
    records = [
        {**turn, "raw": [], "error": None, "follow_up_actions": None}
        for turn in (turn_one, turn_two)
    ]
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
    config = EvalConfig(providers={}, rotation_order=[], default_max_usd=0.0, judge={})
    transport = ChatStreamTransport()
    with (
        patch.object(transport, "_mint_user", AsyncMock(return_value="u@gaia.local")),
        patch.object(transport, "_stream_turn", AsyncMock(side_effect=records)),
    ):
        run = await transport.run(_case(), config, EvalCostTracker({"p": provider}, 1.0), provider)

    assert run.tool_calls == [HANDOFF]
    assert run.final_turn_tool_calls == []
    assert quality.turns_for(_case()) == TURNS
