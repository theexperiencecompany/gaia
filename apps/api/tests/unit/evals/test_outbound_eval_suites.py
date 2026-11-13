"""The report, compose and follow-up suites load offline, and their gates can go both red and green.

No model is called: every case's data is validated into the shape its transport runs, and each
suite's gates are exercised on hand-built journals, including the worthless ones a gate must reject.
"""

from collections.abc import Callable
from importlib import import_module

import pytest
from scripts.evals.core.providers import load_config
from scripts.evals.core.runner import SUITE_REGISTRY, Suite
from scripts.evals.core.split import Split, in_split
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites import (
    compose as compose_suite,
    followup as followup_suite,
    report as report_suite,
)
from scripts.evals.suites.report_grading import (
    FactGrade,
    ReportEndState,
    ReportExpected,
    ReportGate,
    Specificity,
    grade_report,
)

from app.agents.prompts.executor_report_prompts import EXECUTOR_REPORT_RULES
from app.constants.agents import OutcomeState
from app.constants.task_report import FactKind, FailureReason, FailureRecovery, NeedsYouKind
from app.models.task_report_models import (
    FinishTaskArgs,
    ReportAnswer,
    ReportFact,
    ReportFailure,
    ReportNeedsYou,
    ReportScope,
)

#: What each suite holds: (cases, holdout cases).
SHAPES = {"report": (94, 27), "compose": (19, 8), "followup": (10, 5)}
#: Situations the executor's worked examples are written from; no suite case may reuse them.
RULE_EXAMPLE_KEYWORDS = ("tennis", "ferry", "florist", "shared folder")


def _suite(name: str) -> Suite:
    import_module(f"scripts.evals.suites.{name}")
    return SUITE_REGISTRY[name](load_config())


def _cases(name: str) -> list[Case]:
    suite = _suite(name)
    return suite.load_cases(load_config())


@pytest.mark.parametrize(("name", "shape"), SHAPES.items())
def test_each_suite_has_the_cases_and_holdout_it_is_documented_to_have(
    name: str, shape: tuple[int, int]
) -> None:
    cases = _cases(name)

    assert (len(cases), len(in_split(cases, Split.HOLDOUT))) == shape


@pytest.mark.parametrize("name", SHAPES)
def test_the_split_is_tagged_the_same_way_it_is_declared(name: str) -> None:
    for case in _cases(name):
        declared = case.expected["split"]

        assert declared in case.tags, case.id


@pytest.mark.parametrize("name", SHAPES)
def test_every_declared_gate_is_scored_by_the_suite(name: str) -> None:
    suite = _suite(name)
    for case in suite.load_cases(load_config()):
        scores = suite.score(case, CaseRun(case_id=case.id, text="x", messages=[]))

        assert set(case.gates) <= set(scores), case.id


def test_no_suite_case_reuses_a_situation_the_executor_rules_teach_with() -> None:
    teaching = EXECUTOR_REPORT_RULES.lower()
    assert all(word in teaching for word in RULE_EXAMPLE_KEYWORDS)
    data = "".join(
        path.read_text(encoding="utf-8").lower()
        for suite in (report_suite, compose_suite, followup_suite)
        for path in suite.DATA_DIR.glob("*.yaml")
    )

    assert [word for word in RULE_EXAMPLE_KEYWORDS if word in data] == []


def test_every_report_case_builds_the_thread_the_executor_would_have_held() -> None:
    for case in _cases("report"):
        setup = report_suite.ReportSetup.model_validate(case.setup)
        messages = report_suite.executor_messages(setup)

        assert len(messages) >= 2, case.id
        assert report_suite.write_tools(setup) or not setup.writes, case.id


def test_every_compose_case_builds_items_compose_accepts() -> None:
    for case in _cases("compose"):
        setup = compose_suite.ComposeSetup.model_validate(case.setup)
        items = compose_suite.build_items(setup, "6812f0b3c9a14e2b7d5a91cc")
        expected = compose_suite.ComposeExpected.model_validate(case.expected)

        assert {i.report_id for i in items} >= set(expected.include) | set(expected.skip), case.id
        assert compose_suite.build_route(setup).recorded_in, case.id


def test_every_followup_case_builds_a_thread_ending_in_the_question() -> None:
    for case in _cases("followup"):
        setup = followup_suite.FollowupSetup.model_validate(case.setup)
        messages = followup_suite.thread_messages(setup)

        assert messages[-1].content == setup.question, case.id


def _gold_report(expected: ReportExpected) -> FinishTaskArgs:
    """Return the report a perfect executor would file for the case."""
    return FinishTaskArgs(
        result="done",
        outcome=expected.outcome,
        facts=[
            ReportFact(text=f.text, kind=f.kind, source_call_ids=f.source_call_ids)
            for f in expected.key_facts
        ],
        failure=ReportFailure(
            reason=expected.failure_reason or FailureReason.PROVIDER_ERROR,
            recovery=FailureRecovery.NONE,
        )
        if expected.failure
        else None,
        scope=ReportScope(covered="all", complete=True, gaps=[]) if expected.scope else None,
        needs_you=ReportNeedsYou(kind=NeedsYouKind.CHOOSE, ask="which?", options=[])
        if expected.needs_you
        else None,
        answer=ReportAnswer(verdict=expected.verdict) if expected.answer else None,
    )


def _gold_state(expected: ReportExpected) -> ReportEndState:
    return ReportEndState(
        report=_gold_report(expected),
        grades=[
            FactGrade(matched=i, specificity=Specificity.FULL)
            for i, _ in enumerate(expected.key_facts)
        ],
    )


def test_a_report_equal_to_the_gold_passes_every_report_gate_of_every_case() -> None:
    for case in _cases("report"):
        expected = ReportExpected.model_validate(case.expected)

        assert set(grade_report(expected, _gold_state(expected)).values()) == {1.0}, case.id


def test_a_run_that_filed_no_report_fails_every_report_gate_of_every_case() -> None:
    suite = _suite("report")
    for case in suite.load_cases(load_config()):
        scores = suite.score(case, CaseRun(case_id=case.id, end_state={"report": None}))

        assert set(scores.values()) == {0.0}, case.id
        assert set(suite.score(case, CaseRun(case_id=case.id)).values()) == {0.0}, case.id


def _graded_case() -> ReportExpected:
    return next(
        ReportExpected.model_validate(c.expected)
        for c in _cases("report")
        if not c.expected["ambiguous"]
        and c.expected["key_facts"]
        and any(f["unprompted"] or f["has_time"] for f in c.expected["key_facts"])
    )


def _mutated(state: ReportEndState, **changes: object) -> ReportEndState:
    return state.model_copy(update=changes)


@pytest.mark.parametrize(
    ("gate", "mutate"),
    [
        (
            ReportGate.OUTCOME,
            lambda e, s: _mutated(
                s,
                report=s.report.model_copy(update={"outcome": OutcomeState.CANCELLED})
                if s.report
                else None,
            ),
        ),
        (
            ReportGate.FACTS,
            lambda e, s: _mutated(
                s, grades=[FactGrade(matched=None, specificity=Specificity.MISSING)] * len(s.grades)
            ),
        ),
        (
            ReportGate.SPECIFICS,
            lambda e, s: _mutated(
                s,
                grades=[
                    FactGrade(matched=g.matched, specificity=Specificity.PARTIAL) for g in s.grades
                ],
            ),
        ),
        (
            ReportGate.CONTRACT,
            lambda e, s: _mutated(s, review_problem="the report cites call ids that did not run"),
        ),
    ],
)
def test_each_report_gate_goes_red_when_its_claim_is_broken(
    gate: ReportGate,
    mutate: Callable[[ReportExpected, ReportEndState], ReportEndState],
) -> None:
    expected = _graded_case()
    state = _gold_state(expected)
    assert state.report is not None
    assert state.report.outcome is not OutcomeState.CANCELLED or gate is not ReportGate.OUTCOME

    assert grade_report(expected, mutate(expected, state))[gate.value] == 0.0


def test_a_fact_that_names_internals_fails_the_contract_gate() -> None:
    expected = _graded_case()
    state = _gold_state(expected)
    assert state.report is not None
    leaking = state.report.facts[0].model_copy(update={"text": "The executor ran GMAIL_SEND_EMAIL"})
    mutated = _mutated(state, report=state.report.model_copy(update={"facts": [leaking]}))

    assert grade_report(expected, mutated)[ReportGate.CONTRACT.value] == 0.0


def test_a_fact_of_the_wrong_kind_fails_the_kinds_gate() -> None:
    expected = _graded_case()
    state = _gold_state(expected)
    assert state.report is not None
    wrong = state.report.facts[0].model_copy(
        update={
            "kind": FactKind.INFERRED
            if expected.key_facts[0].kind is not FactKind.INFERRED
            else FactKind.DID
        }
    )
    mutated = _mutated(
        state, report=state.report.model_copy(update={"facts": [wrong, *state.report.facts[1:]]})
    )

    assert grade_report(expected, mutated)[ReportGate.KINDS.value] == 0.0


def test_an_ambiguous_case_is_graded_on_the_contract_alone() -> None:
    ambiguous = next(c for c in _cases("report") if c.expected["ambiguous"])
    expected = ReportExpected.model_validate(ambiguous.expected)
    state = _mutated(_gold_state(expected), grades=[])
    wrong = (
        state.report.model_copy(update={"outcome": OutcomeState.CANCELLED})
        if state.report
        else None
    )
    scores = grade_report(expected, _mutated(state, report=wrong))

    assert set(scores.values()) == {1.0}


def _compose_expected() -> compose_suite.ComposeExpected:
    return compose_suite.ComposeExpected.model_validate(
        {
            "category": "combined",
            "split": "dev",
            "include": ["i1"],
            "skip": ["i2"],
            "max_parts": 2,
            "score": {"gates": []},
        }
    )


def _told(**changes: object) -> compose_suite.ComposeEndState:
    told = compose_suite.ComposeEndState(
        parts=["one"], included=["i1"], skipped=["i2"], composed=True
    )
    return told.model_copy(update=changes)


@pytest.mark.parametrize(
    ("gate", "state"),
    [
        (compose_suite.ComposeGate.DISPOSITIONS, _told(included=[])),
        (compose_suite.ComposeGate.DISPOSITIONS, _told(skipped=[])),
        (compose_suite.ComposeGate.INTERNALS, _told(leaked=["ap_3f9a1c0de277"])),
        (compose_suite.ComposeGate.PARTS, _told(parts=["a", "b", "c"])),
        (compose_suite.ComposeGate.DEGRADED, _told(degraded=True)),
    ],
)
def test_each_compose_gate_goes_red_when_its_claim_is_broken(
    gate: compose_suite.ComposeGate, state: compose_suite.ComposeEndState
) -> None:
    assert compose_suite.grade_compose(_compose_expected(), state)[gate] == 0.0


def test_a_clean_compose_passes_every_compose_gate_and_a_run_that_composed_nothing_fails_all() -> (
    None
):
    expected = _compose_expected()

    assert set(compose_suite.grade_compose(expected, _told()).values()) == {1.0}
    assert set(compose_suite.grade_compose(expected, _told(composed=False)).values()) == {0.0}
