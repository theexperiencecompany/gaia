"""The outbox policy: a pure decision per report."""

from datetime import UTC, datetime

import pytest

from app.constants.agents import OutcomeState
from app.models.ownership_models import DeliveryPolicy, DeliveryTiming
from app.models.task_report_models import TaskReport
from app.services.outbox.models import (
    ComposeMode,
    DropReason,
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
    UrgencyClass,
)
from app.services.outbox.policy import DecisionKind, decide, is_answer, must_include

SUBJECT = Subject(kind=SubjectKind.TODO_RUN, id="s", label="L")


def _run(
    outcome: OutcomeState | None, initiative: Initiative = Initiative.SELF_INITIATED
) -> RunReport:
    return RunReport(
        report_id="r",
        recipient="u",
        producer=ProducerKind.TODO,
        subject=SUBJECT,
        occurred_at=datetime(2026, 11, 10, tzinfo=UTC),
        initiative=initiative,
        report=TaskReport(outcome=outcome),
    )


def _notice(**overrides: object) -> NoticeReport:
    fields: dict[str, object] = {
        "report_id": "n",
        "recipient": "u",
        "producer": ProducerKind.REMINDER,
        "subject": SUBJECT,
        "occurred_at": datetime(2026, 11, 10, tzinfo=UTC),
        "initiative": Initiative.USER_SCHEDULED,
        "outcome": NoticeOutcome.INFO,
        "facts": ["x"],
    }
    return NoticeReport.model_validate({**fields, **overrides})


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (OutcomeState.NOTHING_NEW, DropReason.NOTHING_NEW),
        (OutcomeState.CANCELLED, DropReason.CANCELLED),
    ],
)
def test_a_run_with_nothing_to_tell_is_recorded_only(
    outcome: OutcomeState, reason: DropReason
) -> None:
    decision = decide(_run(outcome))

    assert (decision.kind, decision.drop_reason) == (DecisionKind.RECORD_ONLY, reason)


@pytest.mark.parametrize("outcome", [OutcomeState.DONE, OutcomeState.NO_ACTION_NEEDED])
def test_a_run_with_a_result_is_sent(outcome: OutcomeState) -> None:
    decision = decide(_run(outcome))

    assert (decision.kind, decision.drop_reason) == (DecisionKind.SEND_NOW, None)


@pytest.mark.parametrize(
    "outcome",
    [OutcomeState.FAILED, OutcomeState.NEEDS_YOU, OutcomeState.PARTIAL, OutcomeState.UNVERIFIED],
)
def test_what_the_user_must_act_on_is_timely_and_must_be_said(outcome: OutcomeState) -> None:
    report = _run(outcome)

    assert decide(report).urgency is UrgencyClass.TIMELY
    assert must_include(UrgencyClass.TIMELY, report)


def test_a_self_initiated_result_starts_as_background_and_may_be_skipped() -> None:
    report = _run(OutcomeState.DONE)

    assert decide(report).urgency is UrgencyClass.BACKGROUND
    assert not must_include(UrgencyClass.BACKGROUND, report)


def test_an_answer_must_be_said_whatever_its_class() -> None:
    report = _run(OutcomeState.DONE, Initiative.ASKED)

    assert is_answer(report)
    assert must_include(UrgencyClass.ROUTINE, report)
    assert decide(report).mode is ComposeMode.ANSWER


def test_a_user_set_time_that_may_wake_is_an_interrupt() -> None:
    decision = decide(
        _notice(delivery_policy=DeliveryPolicy(timing=DeliveryTiming.AT_TIME, may_wake=True))
    )

    assert (decision.urgency, decision.mode) == (UrgencyClass.INTERRUPT, ComposeMode.INTERRUPT)


def test_a_user_set_time_that_may_not_wake_is_not_an_interrupt() -> None:
    decision = decide(_notice(delivery_policy=DeliveryPolicy(timing=DeliveryTiming.AT_TIME)))

    assert decision.urgency is UrgencyClass.ROUTINE


def test_a_run_report_must_declare_its_outcome() -> None:
    with pytest.raises(ValueError, match="declares its outcome"):
        _run(None)


def _muted_run(outcome: OutcomeState) -> RunReport:
    return _run(outcome).model_copy(update={"delivery_policy": DeliveryPolicy(notify=False)})


@pytest.mark.parametrize(
    "outcome",
    [
        OutcomeState.DONE,
        OutcomeState.NO_ACTION_NEEDED,
        OutcomeState.SCHEDULE,
        OutcomeState.SUBSCRIBE,
    ],
)
def test_a_muted_producers_result_is_recorded_and_never_alerted(outcome: OutcomeState) -> None:
    decision = decide(_muted_run(outcome))

    assert decision.kind is DecisionKind.RECORD_ONLY
    assert decision.drop_reason is DropReason.USER_MUTED


@pytest.mark.parametrize(
    "outcome",
    [
        OutcomeState.NEEDS_YOU,
        OutcomeState.FAILED,
        OutcomeState.PARTIAL,
        OutcomeState.BLOCKED,
        OutcomeState.UNVERIFIED,
    ],
)
def test_a_muted_producer_still_tells_what_needs_the_user(outcome: OutcomeState) -> None:
    decision = decide(_muted_run(outcome))

    assert decision.kind is DecisionKind.SEND_NOW
    assert decision.urgency is UrgencyClass.TIMELY


def test_nothing_new_keeps_its_own_reason_under_a_mute() -> None:
    assert decide(_muted_run(OutcomeState.NOTHING_NEW)).drop_reason is DropReason.NOTHING_NEW


def test_a_muted_notice_that_needs_the_user_is_sent() -> None:
    muted = DeliveryPolicy(notify=False)

    assert (
        decide(_notice(delivery_policy=muted, outcome=NoticeOutcome.FAILED)).kind
        is DecisionKind.SEND_NOW
    )
    assert (
        decide(_notice(delivery_policy=muted, outcome=NoticeOutcome.INFO)).drop_reason
        is DropReason.USER_MUTED
    )


def test_progress_nobody_is_watching_is_recorded_and_never_alerted() -> None:
    decision = decide(_notice(outcome=NoticeOutcome.PROGRESS), watched_live=False)

    assert (decision.kind, decision.drop_reason) == (
        DecisionKind.RECORD_ONLY,
        DropReason.NOT_WATCHING,
    )


def test_progress_someone_is_watching_live_is_sent() -> None:
    decision = decide(_notice(outcome=NoticeOutcome.PROGRESS), watched_live=True)

    assert (decision.kind, decision.drop_reason) == (DecisionKind.SEND_NOW, None)


@pytest.mark.parametrize("outcome", [NoticeOutcome.INFO, NoticeOutcome.NEEDS_YOU])
def test_only_progress_depends_on_being_watched(outcome: NoticeOutcome) -> None:
    assert decide(_notice(outcome=outcome), watched_live=False).kind is DecisionKind.SEND_NOW


def test_a_handoff_that_needs_the_user_is_timely_whether_or_not_they_are_watching() -> None:
    report = _notice(outcome=NoticeOutcome.NEEDS_YOU, initiative=Initiative.ASKED)

    assert decide(report, watched_live=False).urgency is UrgencyClass.TIMELY
