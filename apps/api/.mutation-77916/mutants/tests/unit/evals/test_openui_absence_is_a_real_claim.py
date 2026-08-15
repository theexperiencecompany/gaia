"""``openui: false`` must be able to go red.

The branch returned ``1.0`` with the reason "not expected" without reading the
output at all, so a case declaring "no component belongs in this reply" scored a
pass whatever the agent emitted — a check that cannot fail, carrying the
authority of one that can. It was invisible to both safety nets: the forgery
sweep only asks whether a gate rejects a worthless run (it did not), and the
inert check only asks whether a gate produces a value (it did — always the same
one).

Absence is a real claim, so it is asserted in both directions here, and — per
the rule every other absence gate in this module follows — a run that produced
nothing cannot satisfy it, because "no violation found" and "nothing to inspect"
are different answers.
"""

from __future__ import annotations

from typing import Any

import pytest
from scripts.evals.core.scorers import NOTHING_TO_INSPECT, OpenUICheck

FENCE = ':::openui\n{"component": "Stat", "props": {"value": 42}}\n:::'
FORBIDDEN: dict[str, Any] = {"openui": False}
REQUIRED: dict[str, Any] = {"openui": True}


def test_a_forbidden_fence_that_was_emitted_fails() -> None:
    result = OpenUICheck().score(output=f"here you go\n{FENCE}", expected=FORBIDDEN)

    assert result.value == 0.0
    assert "forbids" in result.reason


def test_an_unterminated_forbidden_fence_still_fails() -> None:
    # The full-fence pattern needs a closing ':::' — a truncated component is
    # still a component the agent should not have started.
    result = OpenUICheck().score(output=':::openui\n{"component": "Stat"', expected=FORBIDDEN)

    assert result.value == 0.0


def test_a_fence_in_an_earlier_bubble_still_fails() -> None:
    result = OpenUICheck().score(
        output="anything else?",
        messages=[
            {"role": "user", "content": "how am I doing?"},
            {"role": "assistant", "content": FENCE},
            {"role": "assistant", "content": "anything else?"},
        ],
        expected=FORBIDDEN,
    )

    assert result.value == 0.0


def test_prose_with_no_fence_passes() -> None:
    result = OpenUICheck().score(
        output="you're on track for the week — nothing needs your attention.", expected=FORBIDDEN
    )

    assert result.value == 1.0
    assert result.reason == "no OpenUI fence, as required"


def test_a_run_that_produced_nothing_cannot_satisfy_the_absence_claim() -> None:
    result = OpenUICheck().score(output="", messages=[], tool_calls=[], expected=FORBIDDEN)

    assert result.value == 0.0
    assert result.reason == NOTHING_TO_INSPECT


@pytest.mark.parametrize(
    ("output", "value"),
    [(FENCE, 1.0), ("no component here", 0.0), (":::openui\nnot json\n:::", 0.0)],
)
def test_the_required_direction_is_unchanged(output: str, value: float) -> None:
    assert OpenUICheck().score(output=output, expected=REQUIRED).value == value
