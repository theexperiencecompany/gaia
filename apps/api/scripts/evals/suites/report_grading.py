"""How an executor's report is graded against a case's gold: pure, so a journaled run is regraded for free.

The report is the real finish_task report (app.models.task_report_models.FinishTaskArgs). Facts are
matched to the gold by a grader model once, per run, and stored beside the report; every gate below
reads only that record, so editing a gate never costs a model call.
"""

from __future__ import annotations

from enum import StrEnum
import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.constants.agents import OutcomeState
from app.constants.task_report import AnswerVerdict, FactKind, FailureReason
from app.models.task_report_models import FinishTaskArgs
from scripts.evals.core.split import Split
from scripts.evals.core.types import Case, CaseRun

#: What a user must never read in a fact: tool-style names, call ids, 24-hex ids, the executor's own words.
INTERNALS: Final = re.compile(
    r"\b([A-Z][A-Z0-9]+_[A-Z0-9_]{2,}|call_id|c\d{1,3}\b|executor|subagent|tool call|task_id|[0-9a-f]{24})\b"
)


class ReportGate(StrEnum):
    """The gates a report case declares."""

    OUTCOME = "report_outcome"
    FACTS = "report_facts"
    SPECIFICS = "report_specifics"
    KINDS = "report_kinds"
    SHAPE = "report_shape"
    CONTRACT = "report_contract"


class Specificity(StrEnum):
    """How much of a gold fact's specifics the reported facts carry, judged by what a follow-up would need."""

    FULL = "full"
    PARTIAL = "partial"
    MISSING = "missing"


class FactGrade(BaseModel):
    """The grader's reading of one gold fact against the reported facts."""

    matched: int | None = Field(
        description="Index of the reported fact that conveys the gold fact's core claim, null when none does."
    )
    specificity: Specificity = Field(
        description=(
            "full: the reported facts carry the core claim and the specifics a follow-up would need "
            "(names, amounts, dates, the concrete ask). partial: the claim is there, the specifics "
            "the user would ask about next are not. missing: not conveyed."
        )
    )


class FactGrades(BaseModel):
    """One grade per gold fact, in the gold's order."""

    grades: list[FactGrade]


class GoldFact(BaseModel):
    """One fact the report has to carry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    kind: FactKind
    source_call_ids: list[str]
    unprompted: bool
    has_time: bool
    has_counterparty: bool

    @property
    def is_critical(self) -> bool:
        """Whether the user is harmed by its absence: a deadline or something they did not ask about."""
        return self.unprompted or self.has_time


class ReportExpected(BaseModel):
    """A case's gold: the outcome, the facts, and which optional sections the report must (not) carry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    split: Split
    #: Two careful labellers disagree: the run is graded on the contract alone.
    ambiguous: bool
    outcome: OutcomeState
    key_facts: list[GoldFact]
    failure: bool
    scope: bool
    #: None where the approval system, not the model, reports what the user must do.
    needs_you: bool | None
    answer: bool
    failure_reason: FailureReason | None = None
    verdict: AnswerVerdict | None = None
    score: dict[str, list[str]]


class ReportEndState(BaseModel):
    """What one run journals: the report it filed, how the run's own calls judged it, and the fact grades."""

    #: A run journaled in another shape (a forgery, an older record) reads as one that filed nothing.
    model_config = ConfigDict(extra="ignore")

    report: FinishTaskArgs | None = None
    review_problem: str | None = None
    grades: list[FactGrade] = Field(default_factory=list)


def _facts_match(state: ReportEndState) -> bool:
    return all(grade.matched is not None for grade in state.grades)


def _specifics_carried(expected: ReportExpected, state: ReportEndState) -> bool:
    pairs = list(zip(expected.key_facts, state.grades, strict=True))
    judged = [pair for pair in pairs if pair[0].is_critical] or pairs
    return all(
        grade.matched is not None and grade.specificity is Specificity.FULL for _, grade in judged
    )


def _kinds_match(report: FinishTaskArgs, expected: ReportExpected, state: ReportEndState) -> bool:
    for gold, grade in zip(expected.key_facts, state.grades, strict=True):
        if grade.matched is None or grade.matched >= len(report.facts):
            return False
        if report.facts[grade.matched].kind is not gold.kind:
            return False
    return True


def _shape_matches(report: FinishTaskArgs, expected: ReportExpected) -> bool:
    if (report.failure is not None) != expected.failure:
        return False
    if (
        expected.failure_reason is not None
        and report.failure is not None
        and report.failure.reason is not expected.failure_reason
    ):
        return False
    if (report.scope is not None) != expected.scope or (
        report.answer is not None
    ) != expected.answer:
        return False
    if expected.needs_you is not None and (report.needs_you is not None) != expected.needs_you:
        return False
    if expected.verdict is not None:
        return report.answer is not None and report.answer.verdict is expected.verdict
    return True


def _contract_kept(report: FinishTaskArgs, state: ReportEndState) -> bool:
    return state.review_problem is None and not any(
        INTERNALS.search(fact.text) for fact in report.facts
    )


def grade_report(expected: ReportExpected, state: ReportEndState) -> dict[str, float]:
    """Return each gate's score: 1.0 or 0.0. A run that filed no valid report fails them all.

    An ambiguous case is graded on the contract alone: its gold is not one the labellers agree on.
    """
    report = state.report
    if report is None:
        return {gate.value: 0.0 for gate in ReportGate}
    graded = not expected.ambiguous
    results = {
        ReportGate.OUTCOME: not graded or report.outcome is expected.outcome,
        ReportGate.FACTS: not graded or _facts_match(state),
        ReportGate.SPECIFICS: not graded or _specifics_carried(expected, state),
        ReportGate.KINDS: not graded or _kinds_match(report, expected, state),
        ReportGate.SHAPE: not graded or _shape_matches(report, expected),
        ReportGate.CONTRACT: _contract_kept(report, state),
    }
    return {gate.value: float(kept) for gate, kept in results.items()}


def gate_score(gate: ReportGate, case: Case, run: CaseRun) -> float:
    """Score one gate of a journaled run; a run that journaled nothing scores 0."""
    if not run.end_state:
        return 0.0
    expected = ReportExpected.model_validate(case.expected)
    return grade_report(expected, ReportEndState.model_validate(run.end_state))[gate.value]
