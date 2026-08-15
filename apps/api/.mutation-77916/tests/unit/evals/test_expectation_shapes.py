"""An expectation written in the wrong shape must never disable its gate.

``expected`` reaches a scorer typed ``object`` because it comes from
user-written YAML, and iterating a scalar succeeds silently:
``must_not_call_tools: send_email`` yields the characters ``s``, ``e``, ``n``…
so no entry ever equals a real tool name and the gate goes green whatever the
agent called. The same shape mistake turns ``communicate`` into a per-character
check, and a scalar ``judge:`` raised ``AttributeError`` from inside the judge
instead of scoring anything.

The gate must still be able to go red — a wrong shape is a case-authoring bug,
not a licence to pass.
"""

from __future__ import annotations

from typing import Any

import pytest
from scripts.evals.core.scorers import (
    CommunicateGate,
    NoForbiddenToolCalls,
    RubricJudge,
    ToolCallCorrectness,
)

MESSAGES = [
    {"role": "user", "content": "email the invoice to priya"},
    {"role": "assistant", "content": "sent it"},
]
SENT_EMAIL: list[dict[str, Any]] = [{"name": "send_email", "args": {"to": "priya@northwind.io"}}]


@pytest.mark.parametrize("forbidden", ["send_email", {"tool": "send_email"}, 7])
def test_a_scalar_must_not_call_tools_does_not_pass_a_forbidden_call(forbidden: object) -> None:
    result = NoForbiddenToolCalls().score(
        output="sent it",
        tool_calls=SENT_EMAIL,
        messages=MESSAGES,
        expected={"must_not_call_tools": forbidden},
    )

    # Nothing is asserted as forbidden, so the honest verdict is "no tools
    # forbidden" — what must never happen is a green that claims send_email was
    # checked and absent.
    assert "none of" not in result.reason


def test_a_list_must_not_call_tools_still_catches_the_call() -> None:
    result = NoForbiddenToolCalls().score(
        output="sent it",
        tool_calls=SENT_EMAIL,
        messages=MESSAGES,
        expected={"must_not_call_tools": ["send_email"]},
    )

    assert result.value == 0.0
    assert "send_email" in result.reason


def test_a_scalar_communicate_is_not_checked_character_by_character() -> None:
    result = CommunicateGate().score(
        output="", messages=MESSAGES, expected={"communicate": "priya@northwind.io"}
    )

    assert result.reason == "nothing required"


def test_a_communicate_list_still_fails_on_a_missing_string() -> None:
    result = CommunicateGate().score(
        output="", messages=MESSAGES, expected={"communicate": ["priya@northwind.io"]}
    )

    assert result.value == 0.0


def test_a_scalar_tool_calls_expectation_does_not_iterate_characters() -> None:
    result = ToolCallCorrectness().score(
        output="", tool_calls=SENT_EMAIL, expected={"tool_calls": "send_email"}
    )

    assert result.reason == "no tool calls expected"


def test_a_string_min_calls_is_still_enforced() -> None:
    result = ToolCallCorrectness().score(
        output="",
        tool_calls=SENT_EMAIL,
        expected={"tool_calls": [{"tool": "send_email", "min_calls": "2"}]},
    )

    assert result.value == 0.0
    assert "1/2" in result.reason


def test_a_scalar_judge_block_scores_instead_of_raising() -> None:
    judge = RubricJudge(base_url="http://localhost:9", api_key="k", model="m")

    result = judge.score(output="anything", expected={"judge": "be nice"}, messages=MESSAGES)

    assert result.scoring_failed
    assert "no judge criteria" in result.reason
