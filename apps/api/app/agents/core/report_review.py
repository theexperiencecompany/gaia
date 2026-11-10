"""A finish_task report checked against the tool calls that actually ran.

Deterministic and read-only: it names how the report disagrees with the run and
never rewrites the model's account. What a fact says is the model's; whether a
call exists, succeeded, or was a write is the run's.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.constants.agents import OutcomeState
from app.constants.task_report import (
    FINDING_KINDS,
    UNFINISHED_KINDS,
    WRITE_ACCOUNTING_KINDS,
    FactKind,
)
from app.models.task_report_models import TaskReport


@dataclass(frozen=True)
class RunCall:
    """One tool call of the run, as its result and the tool registry describe it."""

    call_id: str
    tool: str
    succeeded: bool
    is_write: bool


def _cited_ids(report: TaskReport, kinds: frozenset[FactKind] | None = None) -> set[str]:
    return {
        call_id
        for fact in report.facts
        if kinds is None or fact.kind in kinds
        for call_id in fact.source_call_ids
    }


def _unknown_calls(report: TaskReport, ran: Mapping[str, RunCall]) -> str | None:
    unknown = sorted(_cited_ids(report) - ran.keys())
    if unknown:
        return f"the report cites call ids that did not run in this task: {', '.join(unknown)}"
    return None


def _did_without_success(report: TaskReport, ran: Mapping[str, RunCall]) -> str | None:
    for fact in report.facts:
        if fact.kind is not FactKind.DID or any(ran[c].succeeded for c in fact.source_call_ids):
            continue
        cited = ", ".join(fact.source_call_ids) or "no call"
        return (
            f"a did fact cites only calls that errored or did no work ({cited}); "
            "did needs a successful call behind it"
        )
    return None


def _unreported_writes(report: TaskReport, ran: Mapping[str, RunCall]) -> str | None:
    accounted = _cited_ids(report, WRITE_ACCOUNTING_KINDS)
    missing = [c for c in ran.values() if c.is_write and c.call_id not in accounted]
    if missing:
        listed = ", ".join(f"{c.tool} ({c.call_id})" for c in missing)
        return (
            "successful write calls are not accounted for by a did, pending_confirmation or "
            f"not_done fact: {listed}"
        )
    return None


def _outcome_contradiction(report: TaskReport) -> str | None:
    unfinished = sorted({f.kind for f in report.facts if f.kind in UNFINISHED_KINDS})
    if report.outcome is OutcomeState.DONE and unfinished:
        return f"outcome done contradicts its {', '.join(unfinished)} fact"
    if report.outcome is OutcomeState.FAILED and report.failure is None:
        return "outcome failed carries no failure"
    return None


def _missing_scope(report: TaskReport) -> str | None:
    if report.scope is not None:
        return None
    if report.outcome is OutcomeState.NOTHING_NEW:
        return "outcome nothing_new carries no scope, so nothing says what was checked"
    if report.answer is not None:
        return "the report carries an answer but no scope of what was read"
    if report.facts and all(f.kind in FINDING_KINDS for f in report.facts):
        return "the report only observes or infers but carries no scope of what was read"
    return None


def report_problem(report: TaskReport, ran: Sequence[RunCall]) -> str | None:
    """Return the first way the report disagrees with the calls that ran, or None."""
    by_id = {call.call_id: call for call in ran}
    return (
        _unknown_calls(report, by_id)
        or _did_without_success(report, by_id)
        or _unreported_writes(report, by_id)
        or _outcome_contradiction(report)
        or _missing_scope(report)
    )
