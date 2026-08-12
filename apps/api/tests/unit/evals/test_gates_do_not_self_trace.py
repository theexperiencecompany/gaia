"""Gates must not log themselves as Opik traces.

``opik``'s ``BaseMetric`` defaults to ``track=True``, which replaces ``score``
with an ``opik.track``-wrapped copy. Inside ``evaluate()`` that attaches a child
span; called directly — which is what :mod:`scripts.evals.core.gates` does for
every case — there is no parent, so each call opens a TOP-LEVEL TRACE named after
the metric, in whatever project ``OPIK_PROJECT_NAME`` points at.

That is not hypothetical: it put 19,235 zero-cost traces named ``end_state``,
``communicate`` and ``tool_call_correctness`` into ``gaia-memory``, against 104
real case traces, and left the project reporting no cost and no tokens at all.

The wrapping is observable without a backend: ``track=True`` assigns an instance
attribute that shadows the class method, so ``"score" in metric.__dict__`` is
True for a tracked metric and False for an untracked one.
"""

from __future__ import annotations

from opik.evaluation.metrics import base_metric, score_result
import pytest
from scripts.evals.core import scorers
from scripts.evals.core.gates import GATES
from scripts.evals.core.scorers import (
    BubbleBoundary,
    CommunicateGate,
    DelegationGate,
    EndStateEquality,
    Gate,
    MustNotCommunicate,
    NoForbiddenToolCalls,
    OpenUICheck,
    ProviderQuality,
    RubricJudge,
    ToolCallCorrectness,
    ToolCard,
)

EVERY_SCORER = [
    BubbleBoundary(),
    CommunicateGate(),
    DelegationGate(),
    EndStateEquality(),
    MustNotCommunicate(),
    NoForbiddenToolCalls(),
    OpenUICheck(),
    ProviderQuality(),
    RubricJudge(base_url="http://unused", api_key="unused", model="unused"),
    ToolCallCorrectness(),
    ToolCard(),
]


def _is_tracked(metric: base_metric.BaseMetric) -> bool:
    """Whether opik replaced ``score`` with a tracked wrapper on this instance."""
    return "score" in metric.__dict__


@pytest.mark.parametrize("metric", EVERY_SCORER, ids=lambda m: m.name)
def test_no_scorer_logs_itself_as_a_trace(metric: base_metric.BaseMetric) -> None:
    assert not _is_tracked(metric), (
        f"{metric.name} is tracked: every direct .score() call will open a top-level "
        f"Opik trace named {metric.name!r} instead of scoring a case"
    )


def test_the_check_can_actually_fail() -> None:
    """A tracked metric must trip the assertion — otherwise the test proves nothing.

    Without this, ``_is_tracked`` returning False for every input would look like
    a clean sweep. This is the mutation check: a deliberately tracked metric has
    to be detected.
    """

    class Tracked(base_metric.BaseMetric):
        def __init__(self) -> None:
            super().__init__("deliberately_tracked", track=True)

        def score(self, **_ignored: object) -> score_result.ScoreResult:
            return score_result.ScoreResult(name=self.name, value=1.0)

    assert _is_tracked(Tracked()), (
        "opik no longer wraps score() on track=True, so this test can no longer "
        "detect a self-tracing gate — find the new signal before trusting it"
    )


def test_gate_base_forces_tracking_off() -> None:
    """The shared base is what makes it impossible to forget at a new call site."""

    class NewScorer(Gate):
        def __init__(self) -> None:
            super().__init__("newly_added")

        def score(self, **_ignored: object) -> score_result.ScoreResult:
            return score_result.ScoreResult(name=self.name, value=1.0)

    assert not _is_tracked(NewScorer())


def test_every_scorer_in_the_module_inherits_the_untracked_base() -> None:
    """A scorer added later must not be able to reintroduce this by accident.

    The parametrised test above only covers the scorers named in this file, so it
    passes forever while a new tracked scorer quietly floods a project. This walks
    the module instead: anything that is an opik metric here has to come through
    :class:`Gate`.
    """
    offenders = [
        name
        for name, obj in vars(scorers).items()
        if isinstance(obj, type)
        and issubclass(obj, base_metric.BaseMetric)
        and obj not in (base_metric.BaseMetric, Gate)
        and not issubclass(obj, Gate)
    ]
    assert not offenders, (
        f"scorers not inheriting Gate: {offenders} — they default to track=True and "
        f"will write one top-level Opik trace per .score() call"
    )


def test_every_registered_gate_name_maps_to_a_module_scorer() -> None:
    """The module walk above only protects what :mod:`gates` actually invokes."""
    assert set(GATES) <= {
        "communicate",
        "must_not_communicate",
        "delegation",
        "tool_call_correctness",
        "no_forbidden_tools",
        "end_state",
        "bubble_boundary",
    }, f"a gate was registered without being covered here: {sorted(GATES)}"
