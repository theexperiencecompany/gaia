"""The decision on a report: tell the user now, or record it and never alert.

Pure: a report in, a Decision out, no I/O, so every rule is provable without a
database. Holds, the Judge, the budget and quiet hours slot in as further inputs
and further kinds of Decision.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.constants.agents import OutcomeState
from app.models.ownership_models import DeliveryTiming
from app.services.outbox.models import (
    ComposeMode,
    DropReason,
    Initiative,
    NoticeOutcome,
    NoticeReport,
    OutboxReport,
    RunReport,
    UrgencyClass,
)

_RECORD_ONLY_OUTCOMES: dict[OutcomeState, DropReason] = {
    OutcomeState.NOTHING_NEW: DropReason.NOTHING_NEW,
    OutcomeState.CANCELLED: DropReason.CANCELLED,
}

_RUN_OUTCOMES_THE_USER_MUST_ACT_ON = frozenset(
    {
        OutcomeState.NEEDS_YOU,
        OutcomeState.FAILED,
        OutcomeState.PARTIAL,
        OutcomeState.BLOCKED,
        OutcomeState.UNVERIFIED,
    }
)
_NOTICE_OUTCOMES_THE_USER_MUST_ACT_ON = frozenset({NoticeOutcome.NEEDS_YOU, NoticeOutcome.FAILED})

#: A delivery timing the user chose themselves: they asked to be told at that moment.
_USER_SET_TIMINGS = frozenset({DeliveryTiming.THE_MOMENT, DeliveryTiming.AT_TIME})


class DecisionKind(StrEnum):
    """What the outbox does with a report."""

    SEND_NOW = "send_now"
    RECORD_ONLY = "record_only"


@dataclass(frozen=True, slots=True)
class Decision:
    """The outcome of the policy for one report; drop_reason is set exactly when it is RECORD_ONLY."""

    kind: DecisionKind
    urgency: UrgencyClass
    mode: ComposeMode
    drop_reason: DropReason | None = None


def is_answer(report: OutboxReport) -> bool:
    """Whether the user asked for it, or scheduled it themselves: never an unsolicited update."""
    return report.initiative in {Initiative.ASKED, Initiative.USER_SCHEDULED}


def _requires_user_action(report: OutboxReport) -> bool:
    match report:
        case RunReport(report=task_report):
            return task_report.outcome in _RUN_OUTCOMES_THE_USER_MUST_ACT_ON
        case NoticeReport(outcome=outcome):
            return outcome in _NOTICE_OUTCOMES_THE_USER_MUST_ACT_ON


def urgency_of(report: OutboxReport) -> UrgencyClass:
    """Return how much the report may interrupt, from what its creator chose and what it says."""
    policy = report.delivery_policy
    if policy.timing in _USER_SET_TIMINGS and policy.may_wake:
        return UrgencyClass.INTERRUPT
    if _requires_user_action(report):
        return UrgencyClass.TIMELY
    if report.initiative is Initiative.SELF_INITIATED:
        return UrgencyClass.BACKGROUND
    return UrgencyClass.ROUTINE


def must_include(urgency: UrgencyClass, report: OutboxReport) -> bool:
    """Whether a message covering this item has to say it: an answer, or timely and above."""
    return is_answer(report) or urgency >= UrgencyClass.TIMELY


def _mode_of(urgency: UrgencyClass, report: OutboxReport) -> ComposeMode:
    if urgency is UrgencyClass.INTERRUPT:
        return ComposeMode.INTERRUPT
    return ComposeMode.ANSWER if is_answer(report) else ComposeMode.UNSOLICITED


def is_progress(report: OutboxReport) -> bool:
    """Whether the report only says where a run is on its way, which is for someone watching it live."""
    return isinstance(report, NoticeReport) and report.outcome is NoticeOutcome.PROGRESS


def decide(report: OutboxReport, *, watched_live: bool = False) -> Decision:
    """Decide what the outbox does with a report that is new and still to be told.

    watched_live says whether the user is on the surface the report's subject lives on now;
    only progress depends on it.
    """
    urgency = urgency_of(report)
    mode = _mode_of(urgency, report)
    if is_progress(report) and not watched_live:
        return Decision(
            DecisionKind.RECORD_ONLY, urgency, mode, drop_reason=DropReason.NOT_WATCHING
        )
    if isinstance(report, RunReport):
        outcome = report.report.outcome
        if outcome in _RECORD_ONLY_OUTCOMES:
            return Decision(
                DecisionKind.RECORD_ONLY, urgency, mode, drop_reason=_RECORD_ONLY_OUTCOMES[outcome]
            )
    if not report.delivery_policy.notify and not _requires_user_action(report):
        return Decision(DecisionKind.RECORD_ONLY, urgency, mode, drop_reason=DropReason.USER_MUTED)
    return Decision(DecisionKind.SEND_NOW, urgency, mode)
