"""The decision on a report: tell the user now, or record it and never alert.

Pure: a report and what the Judge made of it in, a Decision out, no I/O, so every rule is
provable without a database. The Judge decides what an item means; this decides how far that
may move the outbox: it can raise urgency up to a cap, lower it only where the item is not the
user's own words or a security notice, and record an item as not worth telling only when it
is sure. Holds, the budget and quiet hours slot in as further inputs and kinds of Decision.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.constants.agents import OutcomeState
from app.constants.outbox_judge import (
    JUDGE_ANSWER_SUPPRESS_PROBABILITY,
    JUDGE_INTERRUPT_DAILY_CAP,
    JUDGE_SECURITY_TOPIC,
)
from app.models.ownership_models import DeliveryTiming
from app.services.outbox.judge_models import (
    Deadline,
    JudgeVerdict,
    Relevance,
    Sensitivity,
)
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

_NOT_WORTH_TELLING_REASONS: dict[Relevance, DropReason] = {
    Relevance.ALREADY_KNOWN: DropReason.ALREADY_KNOWN,
    Relevance.MOOT: DropReason.MOOT,
    Relevance.SUPERSEDED: DropReason.SUPERSEDED,
    Relevance.DUPLICATE: DropReason.DUPLICATE,
    Relevance.UNWANTED: DropReason.UNWANTED,
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
    sensitivity: Sensitivity = Sensitivity.NONE
    #: The Judge raised this item to interrupt, so it counts against the daily cap.
    raised_interrupt: bool = False
    #: The Judge asked for an interrupt the cap refused; the item is timely instead.
    interrupt_capped: bool = False


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


def waits_for_batch(report: OutboxReport) -> bool:
    """Whether the report waits for its user's other reports before it is judged.

    Answers and interrupts are told as soon as they are judged; everything else gives
    its user's other reports a chance to arrive, so the Judge sees them together.
    """
    return not is_answer(report) and urgency_of(report) is not UrgencyClass.INTERRUPT


def _mode_of(urgency: UrgencyClass, report: OutboxReport) -> ComposeMode:
    if urgency is UrgencyClass.INTERRUPT:
        return ComposeMode.INTERRUPT
    return ComposeMode.ANSWER if is_answer(report) else ComposeMode.UNSOLICITED


def is_progress(report: OutboxReport) -> bool:
    """Whether the report only says where a run is on its way, which is for someone watching it live."""
    return isinstance(report, NoticeReport) and report.outcome is NoticeOutcome.PROGRESS


def record_only_reason(report: OutboxReport, *, watched_live: bool) -> DropReason | None:
    """Return why a report is recorded and never alerted whatever anyone thinks of it, or None.

    These are the Judge-free decisions: nothing for the Judge to read. watched_live says whether
    the user is on the surface the report's subject lives on now; only progress depends on it.
    """
    if is_progress(report) and not watched_live:
        return DropReason.NOT_WATCHING
    if isinstance(report, RunReport):
        reason = _RECORD_ONLY_OUTCOMES.get(report.report.outcome)
        if reason is not None:
            return reason
    if not report.delivery_policy.notify and not _requires_user_action(report):
        return DropReason.USER_MUTED
    return None


def is_security_notice(verdict: JudgeVerdict) -> bool:
    return verdict.sensitivity is Sensitivity.CREDENTIALS or JUDGE_SECURITY_TOPIC in verdict.topics


def is_users_own(report: OutboxReport, producer: UrgencyClass) -> bool:
    """Whether the item is the user's own words or timing: an answer, a reminder, or "the moment"."""
    return (
        is_answer(report)
        or report.delivery_policy.timing in _USER_SET_TIMINGS
        or producer is UrgencyClass.INTERRUPT
    )


def _not_worth_telling(
    report: OutboxReport, producer: UrgencyClass, verdict: JudgeVerdict
) -> DropReason | None:
    """Return why the item is recorded only, when the Judge is sure enough that it is not worth telling."""
    reason = _NOT_WORTH_TELLING_REASONS.get(verdict.relevance)
    if reason is None or is_security_notice(verdict):
        return None
    if is_users_own(report, producer) and (
        verdict.not_worth_probability < JUDGE_ANSWER_SUPPRESS_PROBABILITY
    ):
        return None
    # A repeat of what GAIA already said never hides an item with a deadline.
    if (
        verdict.relevance is Relevance.DUPLICATE
        and verdict.urgency >= UrgencyClass.TIMELY
        and verdict.deadline is not Deadline.NONE
    ):
        return None
    return reason


@dataclass(frozen=True, slots=True)
class _Urgency:
    urgency: UrgencyClass
    raised_interrupt: bool = False
    interrupt_capped: bool = False


def _authorized_urgency(
    report: OutboxReport, producer: UrgencyClass, verdict: JudgeVerdict, raised_today: int
) -> _Urgency:
    judged = verdict.urgency
    if judged > producer:
        if judged is not UrgencyClass.INTERRUPT:
            return _Urgency(judged)
        if raised_today >= JUDGE_INTERRUPT_DAILY_CAP:
            return _Urgency(max(producer, UrgencyClass.TIMELY), interrupt_capped=True)
        return _Urgency(judged, raised_interrupt=True)
    if is_users_own(report, producer) or is_security_notice(verdict):
        return _Urgency(producer)
    return _Urgency(judged)


def decide(
    report: OutboxReport,
    verdict: JudgeVerdict | None,
    *,
    watched_live: bool = False,
    interrupts_raised_today: int = 0,
) -> Decision:
    """Decide what the outbox does with a report that is new and still to be told.

    verdict is None when the Judge was not asked or could not answer: the Rails then decide
    from what the producer set. watched_live only matters for progress.
    """
    producer = urgency_of(report)
    reason = record_only_reason(report, watched_live=watched_live)
    if reason is not None:
        return Decision(DecisionKind.RECORD_ONLY, producer, _mode_of(producer, report), reason)
    if verdict is None:
        return Decision(DecisionKind.SEND_NOW, producer, _mode_of(producer, report))
    authorized = _authorized_urgency(report, producer, verdict, interrupts_raised_today)
    mode = _mode_of(authorized.urgency, report)
    reason = _not_worth_telling(report, producer, verdict)
    if reason is not None:
        return Decision(
            DecisionKind.RECORD_ONLY,
            authorized.urgency,
            mode,
            reason,
            verdict.sensitivity,
        )
    return Decision(
        DecisionKind.SEND_NOW,
        authorized.urgency,
        mode,
        sensitivity=verdict.sensitivity,
        raised_interrupt=authorized.raised_interrupt,
        interrupt_capped=authorized.interrupt_capped,
    )
