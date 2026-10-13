"""A gate a suite does not compute is an auto-FAIL, and nothing else catches it.

runner._status_from_scores reads each declared gate back with
scores.get(gate, 0.0), so an unscored gate is not "ungated" — it is
permanently red. This shipped: CapabilitySuite.score() implemented gates
inline instead of routing through core/gates.py, and
hard-ambiguity-which-client declared no_forbidden_tools that nothing
scored — a perfect run of it scored {} and was journaled failed, reading
the one-case category as 0%. Every suite now dispatches through the shared
registry, and gates.validate_gates rejects an unknown name at load time.

verify cannot see this defect: an unscored gate rejects every forgery, so
the case reports as *proven* while incapable of passing. These tests keep
both true, for the suites whose ground truth lives in data/<suite>/*.yaml.
"""

from __future__ import annotations

import pytest
from scripts.evals.core.gates import validate_gates
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
    """Build a run that does plenty of everything so no gate is skipped for lack of data — a missing key is the defect, not a pass or fail."""
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


def test_an_unimplemented_gate_dies_at_load_time() -> None:
    """The loud load-time failure that replaced a silent 0.0 discovered only after the model calls were already spent."""
    with pytest.raises(ValueError) as raised:
        validate_gates("capability", "some-case", ["a_gate_no_suite_implements"])
    message = str(raised.value)
    assert "some-case" in message
    assert "a_gate_no_suite_implements" in message
    assert "recorded as failed" in message


def test_load_time_validation_accepts_a_suite_local_gate() -> None:
    """Mutation guard: validation must consult the suite's EXTRA_GATES, or every suite-specific gate becomes unusable."""
    from scripts.evals.suites.capability import CapabilitySuite

    validate_gates("capability", "c", ["no_unauthorized_send"], CapabilitySuite.EXTRA_GATES)
    with pytest.raises(ValueError):
        validate_gates("comms", "c", ["no_unauthorized_send"])


class _SuiteThatForgetsAGate:
    """A suite shaped exactly like the defect: declares a gate, never scores it."""

    name = "pretend"

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case, run
        return {"communicate": 1.0}


def test_verify_reports_a_gate_the_suite_never_scores() -> None:
    """Verify's blind spot, closed: an unscored gate used to reject every forgery and report the case as *proven* while unable to pass."""
    from scripts.evals.core.counterfeit import check_case, summary_counts

    case = Case(
        id="pretend-inert-case",
        ticket="t",
        prompt="p",
        expected={
            "communicate": ["x"],
            "must_not_call_tools": ["create_todo"],
            "score": {"gates": ["communicate", "no_forbidden_tools"]},
        },
    )
    verdict = check_case(_SuiteThatForgetsAGate(), case)
    assert verdict.inert == ["no_forbidden_tools"]
    assert not verdict.ok
    assert summary_counts([verdict])["inert"] == 1


def test_a_suite_that_scores_what_it_declares_is_not_reported_inert() -> None:
    """Mutation guard: the check must not flag every case as inert."""
    from scripts.evals.core.counterfeit import check_case

    cfg = load_config()
    suite = next(s for s in _suites(cfg) if s.name == "comms")
    case = suite.load_cases(cfg)[0]
    assert check_case(suite, case).inert == []


#: Cases declaring gates: [], which runner._status_from_scores auto-passes.
#: Held at zero: quality's hard tier and advice families were judge-only,
#: reporting 100% on cases that could not fail; verify agrees on the count.
AUTOPASS_DEBT: dict[str, int] = {
    "capability": 0,
    "quality": 0,
    "comms": 0,
    "safety": 0,
    "hil": 0,
}


@pytest.mark.parametrize("suite_name", AUTHORED_SUITES)
def test_auto_passing_cases_do_not_multiply(suite_name: str) -> None:
    """gates: [] is recorded as PASSED unconditionally (runner line 459)."""
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
