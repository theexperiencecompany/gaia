"""The Rails over the Judge: what its verdict may and may not move."""

from typing import Any

import pytest

from app.constants.outbox_judge import JUDGE_INTERRUPT_DAILY_CAP, JUDGE_SECURITY_TOPIC
from app.models.ownership_models import DeliveryPolicy, DeliveryTiming
from app.services.outbox.judge_models import Deadline, Relevance, Sensitivity
from app.services.outbox.models import (
    ComposeMode,
    DropReason,
    Initiative,
    UrgencyClass,
)
from app.services.outbox.policy import DecisionKind, decide, waits_for_batch
from tests._harness.judge import notice, verdict

MY_REMINDER = {
    "initiative": Initiative.USER_SCHEDULED,
    "delivery_policy": DeliveryPolicy(timing=DeliveryTiming.AT_TIME, may_wake=True),
}


@pytest.mark.parametrize("relevance", [Relevance.MOOT, Relevance.ALREADY_KNOWN, Relevance.UNWANTED])
def test_an_item_the_judge_finds_not_worth_telling_is_recorded_with_that_reason(
    relevance: Relevance,
) -> None:
    decision = decide(notice(), verdict(relevance=relevance, not_worth_probability=0.6))

    assert (decision.kind, decision.drop_reason) == (
        DecisionKind.RECORD_ONLY,
        DropReason(relevance.value),
    )


def test_a_new_item_is_sent() -> None:
    assert decide(notice(), verdict()).kind is DecisionKind.SEND_NOW


def test_a_reminder_the_user_set_is_suppressed_only_when_the_judge_is_sure() -> None:
    unsure = verdict(relevance=Relevance.MOOT, not_worth_probability=0.7)
    sure = verdict(relevance=Relevance.MOOT, not_worth_probability=0.95)

    assert decide(notice(**MY_REMINDER), unsure).kind is DecisionKind.SEND_NOW
    assert decide(notice(**MY_REMINDER), sure).kind is DecisionKind.RECORD_ONLY


def test_an_answer_to_something_the_user_asked_needs_the_same_certainty() -> None:
    asked = notice(initiative=Initiative.ASKED)
    unsure = verdict(relevance=Relevance.ALREADY_KNOWN, not_worth_probability=0.7)

    assert decide(asked, unsure).kind is DecisionKind.SEND_NOW


def test_a_repeat_of_what_gaia_said_never_hides_an_item_with_a_deadline() -> None:
    repeat = {"relevance": Relevance.DUPLICATE, "not_worth_probability": 0.9}

    with_deadline = verdict(**repeat, urgency=UrgencyClass.TIMELY, deadline=Deadline.WITHIN_TODAY)
    without = verdict(**repeat, urgency=UrgencyClass.TIMELY, deadline=Deadline.NONE)

    assert decide(notice(), with_deadline).kind is DecisionKind.SEND_NOW
    assert decide(notice(), without).kind is DecisionKind.RECORD_ONLY


def test_a_security_notice_is_never_recorded_as_not_worth_telling() -> None:
    by_topic = verdict(
        relevance=Relevance.DUPLICATE, not_worth_probability=1.0, topics=[JUDGE_SECURITY_TOPIC]
    )
    by_sensitivity = verdict(
        relevance=Relevance.DUPLICATE,
        not_worth_probability=1.0,
        sensitivity=Sensitivity.CREDENTIALS,
    )

    assert decide(notice(), by_topic).kind is DecisionKind.SEND_NOW
    assert decide(notice(), by_sensitivity).kind is DecisionKind.SEND_NOW


def test_the_judge_may_raise_urgency_and_the_interrupt_is_counted() -> None:
    timely = decide(notice(), verdict(urgency=UrgencyClass.TIMELY))
    interrupt = decide(notice(), verdict(urgency=UrgencyClass.INTERRUPT))

    assert (timely.urgency, timely.raised_interrupt) == (UrgencyClass.TIMELY, False)
    assert (interrupt.urgency, interrupt.mode, interrupt.raised_interrupt) == (
        UrgencyClass.INTERRUPT,
        ComposeMode.INTERRUPT,
        True,
    )


def test_past_the_daily_cap_a_raised_interrupt_is_only_timely() -> None:
    decision = decide(
        notice(),
        verdict(urgency=UrgencyClass.INTERRUPT),
        interrupts_raised_today=JUDGE_INTERRUPT_DAILY_CAP,
    )

    assert (decision.urgency, decision.raised_interrupt, decision.interrupt_capped) == (
        UrgencyClass.TIMELY,
        False,
        True,
    )


def test_a_cap_never_lowers_what_the_producer_already_asked_for() -> None:
    decision = decide(
        notice(delivery_policy=DeliveryPolicy(timing=DeliveryTiming.WHEN_DONE)),
        verdict(urgency=UrgencyClass.INTERRUPT),
        interrupts_raised_today=JUDGE_INTERRUPT_DAILY_CAP,
    )

    assert decision.urgency is UrgencyClass.TIMELY


def test_what_the_user_set_is_not_an_interrupt_the_judge_raised() -> None:
    decision = decide(
        notice(**MY_REMINDER),
        verdict(urgency=UrgencyClass.INTERRUPT),
        interrupts_raised_today=JUDGE_INTERRUPT_DAILY_CAP,
    )

    assert (decision.urgency, decision.raised_interrupt, decision.interrupt_capped) == (
        UrgencyClass.INTERRUPT,
        False,
        False,
    )


def test_the_judge_may_lower_what_the_producer_guessed() -> None:
    decision = decide(notice(outcome="needs_you"), verdict(urgency=UrgencyClass.BACKGROUND))

    assert decision.urgency is UrgencyClass.BACKGROUND


def test_the_judge_cannot_lower_the_users_own_reminder() -> None:
    decision = decide(notice(**MY_REMINDER), verdict(urgency=UrgencyClass.BACKGROUND))

    assert decision.urgency is UrgencyClass.INTERRUPT


def test_the_judge_cannot_lower_what_the_user_asked_for() -> None:
    asked = notice(initiative=Initiative.ASKED, outcome="needs_you")

    assert decide(asked, verdict(urgency=UrgencyClass.BACKGROUND)).urgency is UrgencyClass.TIMELY


def test_the_judge_cannot_lower_a_security_notice() -> None:
    security = verdict(urgency=UrgencyClass.BACKGROUND, topics=[JUDGE_SECURITY_TOPIC])

    assert decide(notice(outcome="failed"), security).urgency is UrgencyClass.TIMELY


def test_sensitivity_is_carried_to_the_decision() -> None:
    assert (
        decide(notice(), verdict(sensitivity=Sensitivity.HEALTH)).sensitivity is Sensitivity.HEALTH
    )


def test_without_a_verdict_the_producer_decides() -> None:
    needs_you = decide(notice(outcome="needs_you"), None)

    assert (needs_you.kind, needs_you.urgency, needs_you.sensitivity) == (
        DecisionKind.SEND_NOW,
        UrgencyClass.TIMELY,
        Sensitivity.NONE,
    )


@pytest.mark.parametrize(
    "report",
    [
        notice(initiative=Initiative.ASKED),
        notice(**MY_REMINDER),
        notice(delivery_policy=DeliveryPolicy(timing=DeliveryTiming.THE_MOMENT, may_wake=True)),
    ],
)
def test_answers_and_interrupts_do_not_wait_for_their_users_other_reports(report: Any) -> None:
    assert waits_for_batch(report) is False


def test_what_the_user_did_not_ask_for_waits_for_their_users_other_reports() -> None:
    assert waits_for_batch(notice()) is True
