"""A gate a suite does not compute is an auto-FAIL, and nothing else catches it.

``runner._status_from_scores`` reads each declared gate back with
``scores.get(gate, 0.0)``. So a case naming a gate its own scorer never emits is
not "ungated" — it is permanently red, whatever the agent did.

That shipped. ``CapabilitySuite.score()`` implements exactly ``communicate`` /
``end_state`` / ``tool_call_correctness`` (plus the ``no_unauthorized_send``
flag) instead of routing through ``core/gates.py``, and
``hard-ambiguity-which-client`` declared ``no_forbidden_tools``. A perfect run of
it — the agent asks which client and creates nothing — scored ``{}`` and was
journaled ``failed``. The category had one case, so the whole category read 0%
and the number was blamed on the agent.

``verify`` cannot see this class of defect: an unscored gate rejects every
forgery, so the case reports as *proven* while being incapable of passing. The
falsifiability sweep asks "can this go red"; this asks the other half, "can it
go green".

The suites here are the ones whose ground truth lives in ``data/<suite>/*.yaml``
— the surface a case author actually writes against.
"""

from __future__ import annotations

import pytest
from scripts.evals.core.providers import EvalConfig, load_config
from scripts.evals.core.runner import Suite
from scripts.evals.core.types import Case, CaseRun

AUTHORED_SUITES = ("capability", "quality", "comms", "safety", "hil")


def _suites(cfg: EvalConfig) -> list[Suite]:
    """Every authored suite, imported through the registry the CLI uses."""
    from importlib import import_module

    from scripts.evals.core.runner import SUITE_REGISTRY

    for name in AUTHORED_SUITES:
        import_module(f"scripts.evals.suites.{name}")
    return [SUITE_REGISTRY[name](cfg) for name in AUTHORED_SUITES]


def _rich_run(case: Case) -> CaseRun:
    """A run that did plenty of everything, so no gate is skipped for lack of data.

    The point is not whether this run passes — it is that every declared gate
    produces a KEY. A gate missing from the dict is the defect.
    """
    return CaseRun(
        case_id=case.id,
        messages=[
            {"role": "user", "content": case.prompt},
            {"role": "assistant", "content": "here is an answer with real content in it"},
        ],
        tool_calls=[{"name": "create_todo", "args": {"title": "something"}}],
        end_state={"verdict": "refuse"},
        text="here is an answer with real content in it",
    )


def test_every_declared_gate_is_computed_by_its_suite() -> None:
    cfg = load_config()
    orphans: list[str] = []
    for suite in _suites(cfg):
        for case in suite.load_cases(cfg):
            scores = suite.score(case, _rich_run(case))
            orphans += [
                f"{suite.name}/{case.id}: gate {gate!r} is never scored"
                for gate in case.gates
                if gate not in scores
            ]
    assert not orphans, (
        "these cases can never pass — their gate is read back as 0.0 for every run:\n"
        + "\n".join(orphans)
    )


def test_the_check_can_actually_fail() -> None:
    """Mutation guard: a case naming a gate nobody implements must be caught."""
    cfg = load_config()
    suite = _suites(cfg)[0]
    invented = Case(
        id="invented",
        ticket="t",
        prompt="p",
        expected={"score": {"gates": ["a_gate_no_suite_implements"]}},
    )
    try:
        scores = suite.score(invented, _rich_run(invented))
    except ValueError:
        # Suites routed through core/gates.py raise on an unknown gate, which is
        # the stronger behaviour — the defect is impossible there by construction.
        return
    assert "a_gate_no_suite_implements" not in scores


def test_capability_gate_names_are_the_ones_the_suite_implements() -> None:
    """Names the live set explicitly, so widening it is a deliberate edit.

    ``no_forbidden_tools`` and ``must_not_communicate`` are NOT in it. They read
    as ordinary gates in YAML and are silently inert here.
    """
    cfg = load_config()
    from scripts.evals.suites.capability import CapabilitySuite

    suite = CapabilitySuite(cfg)
    declared = {gate for case in suite.load_cases(cfg) for gate in case.gates}
    assert declared <= {
        "communicate",
        "end_state",
        "tool_call_correctness",
        "no_unauthorized_send",
    }, (
        "a capability case declares a gate CapabilitySuite.score() does not compute. "
        "Either score it there (ideally by routing through core/gates.py) or express "
        "the claim with a gate that is computed."
    )


#: Cases that declare ``gates: []`` and are therefore recorded as PASSED
#: unconditionally (``runner._status_from_scores`` returns early on an empty gate
#: list). These are pre-existing — quality's original hard tier and its advice
#: families were written judge-only, which is why those categories reported 100%
#: on cases that could not fail. They are the same 43 ``verify`` reports as
#: "judge-only", so the two tools agree on the number.
#:
#: This is a RATCHET, not a blessing. The debt is capped where it was found; a
#: new auto-passing case fails this test. Lower the number as they are fixed.
AUTOPASS_DEBT: dict[str, int] = {
    "capability": 0,
    "quality": 43,
    "comms": 0,
    "safety": 0,
    "hil": 0,
}


@pytest.mark.parametrize("suite_name", AUTHORED_SUITES)
def test_auto_passing_cases_do_not_multiply(suite_name: str) -> None:
    """``gates: []`` is recorded as PASSED unconditionally (runner line 459)."""
    cfg = load_config()
    suite = next(s for s in _suites(cfg) if s.name == suite_name)
    autopass = [
        case.id
        for case in suite.load_cases(cfg)
        if isinstance(case.expected.get("score"), dict) and not case.gates
    ]
    assert len(autopass) <= AUTOPASS_DEBT[suite_name], (
        f"{suite_name}: {len(autopass)} cases declare no gate and are recorded as passed "
        f"no matter what happened, up from the capped {AUTOPASS_DEBT[suite_name]}. "
        f"Give the new one a real gate. Full list: {autopass}"
    )
