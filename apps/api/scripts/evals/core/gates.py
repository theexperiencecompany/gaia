"""Turn a case's declared gates into runtime scores.

``expected.score.gates`` names the checks that decide pass/fail (the runner reads
the same list). This maps each name to the one scorer that implements it, so a
suite never re-implements a check and a gate name means the same thing in every
suite. An unknown gate name raises rather than scoring 0 — a typo in YAML would
otherwise show up as a permanently failing case nobody can explain.

That "otherwise" was not hypothetical. ``CapabilitySuite.score()`` used to
implement three gate names inline instead of coming through here, so a case
declaring ``no_forbidden_tools`` got no entry in the scores dict at all;
``runner._status_from_scores`` reads a missing gate back as ``0.0``, and the case
was permanently red no matter what the agent did. It was the only case in its
category, so the category reported 0% and the agent took the blame. Two things
follow, and both are load-bearing:

* **One implementation per gate name.** A suite-local copy of a shared check is
  a copy that silently diverges; every suite dispatches through :data:`GATES`.
* **A name nothing implements is an ERROR, never a 0.0.** :func:`validate_gates`
  is called from every suite's loader, so the run dies at load time with the case
  id and the known names — before a single model call is spent — instead of
  reporting an agent failure that never happened.

``verify`` cannot catch this class on its own: an unscored gate rejects every
forgery, so the case reports as *proven* while being incapable of passing. It
asks whether a case can go red; this asks whether it can go green.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

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

#: A gate a suite computes inside its own ``score()`` rather than through this
#: dispatcher — a benchmark metric like ``gaia_exact`` or ``probes``, whose value
#: comes from the transport's end state rather than from a reusable check.
#: Declaring it as ``{name: SELF_SCORED}`` tells :func:`validate_gates` the name
#: is real, without claiming this module can produce it.
SELF_SCORED: _Scorer | None = None

#: Every gate name shared across suites, and the single implementation of each.
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
    "bubble_boundary": lambda _case, run: BubbleBoundary().score(messages=run.messages).value,
}

ExtraGates = Mapping[str, _Scorer | None]


def known_gates(extra: ExtraGates | None = None) -> dict[str, _Scorer | None]:
    """The shared gates plus whatever this suite implements for itself."""
    return {**GATES, **dict(extra or {})}


def validate_gates(
    suite: str, case_id: str, gates: list[str], extra: ExtraGates | None = None
) -> None:
    """Reject a gate name nothing implements, at LOAD time.

    Called from every suite's loader. The alternative — discovering it at score
    time — means the failure arrives after the model calls are spent, and looks
    exactly like the agent getting the answer wrong.
    """
    available = known_gates(extra)
    unknown = [gate for gate in gates if gate not in available]
    if unknown:
        raise ValueError(
            f"{suite} case {case_id}: gate(s) {unknown} are not implemented by this suite, so "
            f"every run of it would be recorded as failed. Known here: {sorted(available)}"
        )


def score_gates(case: Case, run: CaseRun, extra: ExtraGates | None = None) -> dict[str, float]:
    """Score every gate the case declares, plus their mean as ``overall``.

    ``extra`` carries the suite's own gates. A name mapped to :data:`SELF_SCORED`
    is validated but not dispatched — its suite fills the value in afterwards.
    """
    available = known_gates(extra)
    scores: dict[str, float] = {}
    for gate in case.gates:
        if gate not in available:
            raise ValueError(
                f"case {case.id}: unknown gate {gate!r} (known: {', '.join(sorted(available))})"
            )
        scorer = available[gate]
        if scorer is not None:
            scores[gate] = scorer(case, run)
    if scores:
        scores["overall"] = round(sum(scores.values()) / len(scores), 3)
    return scores
