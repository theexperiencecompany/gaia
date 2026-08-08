"""Turn a case's declared gates into runtime scores.

``expected.score.gates`` names the checks that decide pass/fail (the runner reads
the same list). This maps each name to the one scorer that implements it, so a
suite never re-implements a check and a gate name means the same thing in every
suite. An unknown gate name raises rather than scoring 0 — a typo in YAML would
otherwise show up as a permanently failing case nobody can explain.
"""

from __future__ import annotations

from collections.abc import Callable

from .scorers import (
    BubbleBoundary,
    CommunicateGate,
    DelegationGate,
    EndStateEquality,
    MustNotCommunicate,
    NoForbiddenToolCalls,
    ToolCallCorrectness,
)
from .types import Case, CaseRun

_Scorer = Callable[[Case, CaseRun], float]

GATES: dict[str, _Scorer] = {
    "communicate": lambda case, run: (
        CommunicateGate()
        .score(output=run.text, messages=run.messages, expected=case.expected)
        .value
    ),
    "must_not_communicate": lambda case, run: (
        MustNotCommunicate()
        .score(output=run.text, messages=run.messages, expected=case.expected)
        .value
    ),
    "delegation": lambda case, run: (
        DelegationGate()
        .score(output=run.text, tool_calls=run.tool_calls, expected=case.expected)
        .value
    ),
    "tool_call_correctness": lambda case, run: (
        ToolCallCorrectness()
        .score(output=run.text, tool_calls=run.tool_calls, expected=case.expected)
        .value
    ),
    "no_forbidden_tools": lambda case, run: (
        NoForbiddenToolCalls()
        .score(output=run.text, tool_calls=run.tool_calls, expected=case.expected)
        .value
    ),
    "end_state": lambda case, run: (
        EndStateEquality()
        .score(output=run.text, end_state=run.end_state, expected=case.expected)
        .value
    ),
    "bubble_boundary": lambda case, run: BubbleBoundary().score(messages=run.messages).value,
}


def score_gates(case: Case, run: CaseRun) -> dict[str, float]:
    """Score every gate the case declares, plus their mean as ``overall``."""
    scores: dict[str, float] = {}
    for gate in case.gates:
        scorer = GATES.get(gate)
        if scorer is None:
            raise ValueError(
                f"case {case.id}: unknown gate {gate!r} (known: {', '.join(sorted(GATES))})"
            )
        scores[gate] = scorer(case, run)
    if scores:
        scores["overall"] = round(sum(scores.values()) / len(scores), 3)
    return scores
