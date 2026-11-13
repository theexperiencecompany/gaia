"""When an item that is to be told is told: the Rails' limits, proved on a pure state."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.constants.outbox_attention import (
    FLUSH_JITTER_MAX_SECONDS,
    MAX_DEFERRALS,
    MAX_HOLD_AGE_SECONDS,
    HoldReason,
)
from app.models.attention_settings_models import AttentionSettings
from app.models.ownership_models import DeliveryPolicy, DeliveryTiming
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS
from app.services.outbox.holds import (
    AttentionState,
    FactHistory,
    Hold,
    Record,
    Tell,
    escalated,
    next_checkin,
    place,
)
from app.services.outbox.judge_verdict import UserClock
from app.services.outbox.models import DropReason, Initiative, ItemHold, UrgencyClass
from app.utils.timezone import Timezone
from tests._harness.judge import notice, verdict

USER = "6812f0b3c9a14e2b7d5a91cc"
DAY = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
NIGHT = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
MORNING = datetime(2026, 11, 11, 8, 0, tzinfo=UTC)
JITTER = timedelta(seconds=FLUSH_JITTER_MAX_SECONDS)
ROUTINE = UrgencyClass.ROUTINE


def _state(now: datetime = DAY, **overrides: Any) -> AttentionState:
    fields: dict[str, Any] = {
        "user_id": USER,
        "now": now,
        "clock": UserClock(Timezone.utc(), DEFAULT_QUIET_HOURS),
        "settings": AttentionSettings(),
        "last_active_at": None,
        "unsolicited_today": 0,
        "last_unsolicited_at": None,
        "fact_history": None,
    }
    return AttentionState(**{**fields, **overrides})


def _held(since: datetime, *, deferrals: int = 0) -> ItemHold:
    return ItemHold(reason=HoldReason.WAIT_FOR_RUN, until=since, since=since, deferrals=deferrals)


def test_a_routine_item_in_the_daytime_with_nothing_against_it_is_told() -> None:
    assert place(notice(), ROUTINE, verdict(), _state()) == Tell()


def test_a_routine_item_in_quiet_hours_waits_for_them_to_end_spread_by_the_jitter() -> None:
    placed = place(notice(), ROUTINE, verdict(), _state(NIGHT))

    assert isinstance(placed, Hold)
    assert placed.reason is HoldReason.QUIET_HOURS
    assert MORNING <= placed.until < MORNING + JITTER


def test_a_user_who_just_wrote_is_told_in_quiet_hours() -> None:
    here = _state(NIGHT, last_active_at=NIGHT - timedelta(minutes=5))

    assert place(notice(), ROUTINE, verdict(), here) == Tell()


def test_an_answer_gets_a_longer_grace_than_an_unsolicited_item() -> None:
    wrote_20_minutes_ago = _state(NIGHT, last_active_at=NIGHT - timedelta(minutes=20))
    answer = notice(initiative=Initiative.ASKED)

    assert place(answer, ROUTINE, verdict(), wrote_20_minutes_ago) == Tell()
    assert isinstance(place(notice(), ROUTINE, verdict(), wrote_20_minutes_ago), Hold)


def test_an_interrupt_crosses_quiet_hours() -> None:
    assert place(notice(), UrgencyClass.INTERRUPT, verdict(), _state(NIGHT)) == Tell()


def test_do_not_disturb_holds_a_judge_raised_interrupt_but_not_the_users_own_reminder() -> None:
    until = NIGHT + timedelta(hours=2)
    dnd = _state(DAY, settings=AttentionSettings(dnd_until=until))
    reminder = notice(
        initiative=Initiative.USER_SCHEDULED,
        delivery_policy=DeliveryPolicy(timing=DeliveryTiming.AT_TIME, may_wake=True),
    )

    assert place(notice(), UrgencyClass.INTERRUPT, verdict(), dnd) == Hold(until, HoldReason.DND)
    assert place(reminder, UrgencyClass.INTERRUPT, verdict(), dnd) == Tell()


def test_a_timely_item_never_misses_its_deadline_because_of_quiet_hours() -> None:
    deadline = NIGHT + timedelta(minutes=45)
    item = verdict(urgency=UrgencyClass.TIMELY, deliver_by=deadline)

    placed = place(notice(), UrgencyClass.TIMELY, item, _state(NIGHT))

    assert placed == Hold(deadline - timedelta(minutes=15), HoldReason.QUIET_HOURS)


def test_a_timely_item_whose_deadline_is_here_is_told_in_quiet_hours() -> None:
    item = verdict(urgency=UrgencyClass.TIMELY, deliver_by=NIGHT + timedelta(minutes=10))

    assert place(notice(), UrgencyClass.TIMELY, item, _state(NIGHT)) == Tell()


def test_a_security_notice_is_told_in_quiet_hours() -> None:
    security = verdict(topics=["security"])

    assert place(notice(), ROUTINE, security, _state(NIGHT)) == Tell()


def test_a_timely_item_in_the_daytime_is_told_whatever_the_budget_says() -> None:
    spent = _state(unsolicited_today=99, last_unsolicited_at=DAY - timedelta(minutes=1))

    assert place(notice(), UrgencyClass.TIMELY, verdict(), spent) == Tell()


def test_an_answer_is_told_whatever_the_budget_and_gap_say() -> None:
    spent = _state(unsolicited_today=99, last_unsolicited_at=DAY - timedelta(minutes=1))

    assert place(notice(initiative=Initiative.ASKED), ROUTINE, verdict(), spent) == Tell()


def test_a_routine_item_over_the_days_budget_waits_for_the_next_check_in() -> None:
    spent = _state(unsolicited_today=6)

    placed = place(notice(), ROUTINE, verdict(), spent)

    assert isinstance(placed, Hold)
    assert placed.reason is HoldReason.CHECKIN
    assert DAY.replace(hour=13) <= placed.until < DAY.replace(hour=13) + JITTER


def test_a_budget_of_zero_leaves_routine_items_to_the_check_ins() -> None:
    silent = _state(settings=AttentionSettings(max_unsolicited_per_day=0))

    assert isinstance(place(notice(), ROUTINE, verdict(), silent), Hold)


def test_an_item_that_waited_for_its_check_in_is_told_there_not_held_again() -> None:
    spent = _state(DAY.replace(hour=13), unsolicited_today=6)

    assert place(notice(), ROUTINE, verdict(), spent, released=True) == Tell()


def test_an_item_whose_deadline_comes_before_the_check_in_is_told_now() -> None:
    soon = verdict(deliver_by=DAY + timedelta(minutes=10))

    assert place(notice(), ROUTINE, soon, _state(unsolicited_today=6)) == Tell()


def test_a_routine_item_too_soon_after_the_last_message_waits_out_the_gap() -> None:
    last = DAY - timedelta(minutes=10)

    placed = place(notice(), ROUTINE, verdict(), _state(last_unsolicited_at=last))

    assert placed == Hold(last + timedelta(minutes=30), HoldReason.GAP)


def test_a_background_item_waits_for_the_next_check_in_or_the_users_return() -> None:
    placed = place(notice(), UrgencyClass.BACKGROUND, verdict(), _state())

    assert isinstance(placed, Hold)
    assert placed.reason is HoldReason.CHECKIN


def test_the_creators_chosen_time_holds_an_item_until_then() -> None:
    tonight = DAY + timedelta(hours=9)
    chosen = notice(delivery_policy=DeliveryPolicy(not_before=tonight))

    assert place(chosen, ROUTINE, verdict(), _state()) == Hold(tonight, HoldReason.NOT_BEFORE)


def test_the_creators_deadline_bounds_a_hold_for_the_budget() -> None:
    by = DAY + timedelta(minutes=50)
    chosen = notice(delivery_policy=DeliveryPolicy(by=by))

    placed = place(chosen, ROUTINE, verdict(), _state(unsolicited_today=6))

    assert placed == Hold(by - timedelta(minutes=15), HoldReason.CHECKIN)


@pytest.mark.parametrize(
    ("told", "ago", "expected"),
    [
        (1, timedelta(hours=12), Record(DropReason.REPEAT_BACKOFF)),
        (1, timedelta(days=2), Tell()),
        (2, timedelta(days=2), Record(DropReason.REPEAT_BACKOFF)),
        (3, timedelta(days=6), Record(DropReason.REPEAT_BACKOFF)),
        (4, timedelta(days=20), Record(DropReason.REPEAT_BACKOFF)),
        (4, timedelta(days=31), Tell()),
    ],
)
def test_a_fact_told_again_and_again_backs_off_one_day_then_three_then_seven_then_a_month(
    told: int, ago: timedelta, expected: Record | Tell
) -> None:
    history = FactHistory(times_told=told, last_told_at=DAY - ago)

    assert place(notice(), ROUTINE, verdict(), _state(fact_history=history)) == expected


def test_a_repeat_with_a_deadline_inside_a_day_is_told_anyway() -> None:
    history = FactHistory(times_told=1, last_told_at=DAY - timedelta(hours=1))
    close = verdict(deliver_by=DAY + timedelta(hours=6))

    assert place(notice(), ROUTINE, close, _state(fact_history=history)) == Tell()


def _waits(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "wait_for_run": "run-1",
        "wait_run_at": DAY + timedelta(minutes=30),
        "wait_run_hit_rate": 0.8,
    }
    return verdict(**{**fields, **overrides})


def test_an_item_waits_for_a_run_worth_waiting_for() -> None:
    run_at = DAY + timedelta(minutes=30)

    assert place(notice(), ROUTINE, _waits(), _state()) == Hold(run_at, HoldReason.WAIT_FOR_RUN)


@pytest.mark.parametrize(
    "run",
    [
        {"wait_run_hit_rate": 0.3},
        {"wait_run_hit_rate": None},
        {"wait_run_at": DAY + timedelta(minutes=50)},
        {"wait_run_at": DAY - timedelta(minutes=1)},
        {"wait_run_at": DAY + timedelta(minutes=30), "deliver_by": DAY + timedelta(minutes=40)},
    ],
)
def test_an_item_does_not_wait_for_a_run_that_is_unlikely_late_or_after_its_deadline(
    run: dict[str, Any],
) -> None:
    assert place(notice(), ROUTINE, _waits(**run), _state()) == Tell()


def test_an_item_waits_for_at_most_so_many_runs_and_so_long() -> None:
    too_many = _held(DAY - timedelta(minutes=20), deferrals=MAX_DEFERRALS)
    too_long = _held(DAY - timedelta(minutes=100))

    assert place(notice(), ROUTINE, _waits(), _state(prior_hold=too_many), released=True) == Tell()
    assert place(notice(), ROUTINE, _waits(), _state(prior_hold=too_long), released=True) == Tell()


def test_an_item_never_waits_for_a_run_when_the_user_asked_for_it() -> None:
    assert place(notice(initiative=Initiative.ASKED), ROUTINE, _waits(), _state()) == Tell()


def test_an_item_held_for_hours_is_promoted_one_class_but_never_to_an_interrupt() -> None:
    stalled = _state(prior_hold=_held(DAY - timedelta(hours=4)))

    assert escalated(UrgencyClass.BACKGROUND, stalled) is UrgencyClass.ROUTINE
    assert escalated(ROUTINE, stalled) is UrgencyClass.TIMELY
    assert escalated(UrgencyClass.TIMELY, stalled) is UrgencyClass.TIMELY
    assert escalated(ROUTINE, _state(prior_hold=_held(DAY - timedelta(hours=1)))) is ROUTINE


def test_no_hold_outlives_the_hold_age_cap_even_in_quiet_hours() -> None:
    old = _held(NIGHT - timedelta(seconds=MAX_HOLD_AGE_SECONDS))

    assert (
        place(notice(), ROUTINE, verdict(), _state(NIGHT, prior_hold=old), released=True) == Tell()
    )


def test_the_next_check_in_is_the_next_slot_on_the_users_own_clock() -> None:
    assert next_checkin(_state(DAY)) == DAY.replace(hour=13)
    assert next_checkin(_state(DAY.replace(hour=19))) == MORNING
    off = DEFAULT_QUIET_HOURS.model_copy(update={"enabled": False})
    no_morning = _state(DAY.replace(hour=19), clock=UserClock(Timezone.utc(), off))
    assert next_checkin(no_morning) == MORNING.replace(hour=13)
