"""Unit tests for the open-state rule: what an open tracked todo must say about its next step."""

from datetime import UTC, datetime, timedelta

import pytest

from app.constants.todos import (
    MAX_HOLD_CHECKS,
    MAX_NEXT_CHECK_AHEAD,
    MAX_REASKS,
    NoReplyPlan,
    WaitingOn,
    WakeReason,
)
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.todos.open_state import (
    WAITING_ON_CHOICES,
    describe_open_state,
    next_check_limit,
    no_reply_plan_words,
    open_state_problems,
    wake_budget_update,
    wake_reason,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
WAITING_ON_MISSING = f"waiting_on is missing: say what this todo waits for: {WAITING_ON_CHOICES}."
SCHEDULED_AT_MISSING = (
    "scheduled_at is missing: set when GAIA next looks at this todo, as an ISO datetime or a "
    "duration from now. Pick it by urgency: hours ('4h') when urgent, days ('3d') for normal "
    "work, up to '2w' for a loose idea."
)
QUESTION_MISSING = "waiting_on='user' needs question: the exact question you asked them."
NO_REPLY_PLAN_MISSING = (
    "waiting_on='user' needs if_no_reply: decide now, while you know why you asked, what "
    "happens if they never answer: 'ask_again' (it matters: ask once more), 'proceed' (carry "
    "out default_action), 'hold' (nothing can move without the answer)."
)


def _todo(**fields: object) -> TodoDocument:
    base: dict[str, object] = {"id": "t1", "user_id": "u1", "title": "t"}
    base.update(fields)
    return TodoDocument.model_validate(base)


def _waiting(on: WaitingOn, days: float = 3, **fields: object) -> TodoDocument:
    return _todo(waiting_on=on, scheduled_at=NOW + timedelta(days=days), **fields)


def _asking(plan: NoReplyPlan | None, **fields: object) -> TodoDocument:
    return _waiting(
        WaitingOn.USER,
        2,
        question="Ship it?",
        if_no_reply=plan,
        default_action="archive it",
        **fields,
    )


class TestWhatMakesAnOpenStateValid:
    @pytest.mark.parametrize("on", [w for w in WaitingOn if w is not WaitingOn.USER])
    def test_every_non_question_state_with_a_future_check_is_valid(self, on):
        assert open_state_problems(_waiting(on), NOW) == []

    def test_a_todo_with_no_next_step_names_both_missing_answers(self):
        problems = open_state_problems(_todo(), NOW)

        assert problems == [WAITING_ON_MISSING, SCHEDULED_AT_MISSING]

    def test_the_waiting_on_message_lists_every_option_so_the_model_can_pick(self):
        (message, _) = open_state_problems(_todo(), NOW)

        for option in ("'time'", "'event'", "'user'", "'sub_todos'", "'unplanned'"):
            assert option in message

    @pytest.mark.parametrize("before_now", [timedelta(0), timedelta(minutes=1)])
    def test_a_check_now_or_in_the_past_is_refused(self, before_now):
        todo = _todo(waiting_on=WaitingOn.TIME, scheduled_at=NOW - before_now)

        assert open_state_problems(todo, NOW) == [
            "scheduled_at is in the past: set a future next check."
        ]

    def test_a_check_up_to_the_limit_and_its_slack_is_valid_and_a_second_more_is_not(self):
        at_limit = NOW + MAX_NEXT_CHECK_AHEAD + timedelta(minutes=5)
        past_limit = at_limit + timedelta(seconds=1)

        assert (
            open_state_problems(_todo(waiting_on=WaitingOn.TIME, scheduled_at=at_limit), NOW) == []
        )
        assert open_state_problems(
            _todo(waiting_on=WaitingOn.TIME, scheduled_at=past_limit), NOW
        ) == [
            "scheduled_at is 14 days out; with waiting_on='time' the next check is at most 14 "
            "days away. A longer wait is fine: look again by then and set the next check from "
            "there."
        ]

    def test_a_long_wait_is_explained_as_fine_if_the_todo_looks_again(self):
        (problem,) = open_state_problems(_waiting(WaitingOn.EVENT, 60), NOW)

        assert problem == (
            "scheduled_at is 60 days out; with waiting_on='event' the next check is at most 14 "
            "days away. A longer wait is fine: look again by then and set the next check from "
            "there."
        )

    def test_a_too_far_check_with_no_waiting_on_names_the_state_generically(self):
        problems = open_state_problems(_todo(scheduled_at=NOW + timedelta(days=60)), NOW)

        assert problems == [
            WAITING_ON_MISSING,
            "scheduled_at is 60 days out; with waiting_on='this state' the next check is at most "
            "14 days away. A longer wait is fine: look again by then and set the next check from "
            "there.",
        ]

    def test_a_recurring_todo_needs_only_its_schedule(self):
        assert open_state_problems(_todo(recurrence="daily", scheduled_at=NOW), NOW) == []
        assert open_state_problems(_todo(recurrence="daily"), NOW) == [
            "recurrence needs scheduled_at: either clear recurrence or provide scheduled_at."
        ]

    def test_a_closed_or_paused_todo_has_nothing_to_wake_for(self):
        assert open_state_problems(_todo(completed=True), NOW) == []
        paused = _todo(pause_reason=DeactivationReason.SUBSCRIPTION_LAPSED)
        assert open_state_problems(paused, NOW) == []


class TestAQuestionToTheUser:
    def test_it_needs_the_question_and_the_plan_for_no_reply(self):
        problems = open_state_problems(_waiting(WaitingOn.USER, 2), NOW)

        assert problems == [QUESTION_MISSING, NO_REPLY_PLAN_MISSING]

    def test_proceed_needs_the_default_it_will_carry_out(self):
        todo = _waiting(WaitingOn.USER, 2, question="q", if_no_reply=NoReplyPlan.PROCEED)

        assert open_state_problems(todo, NOW) == [
            "if_no_reply='proceed' needs default_action: what you will do if they never answer."
        ]

    def test_the_question_may_expire_in_at_most_a_week(self):
        assert open_state_problems(_asking(NoReplyPlan.PROCEED), NOW) == []
        long_wait = _waiting(
            WaitingOn.USER, 8, question="q", if_no_reply=NoReplyPlan.PROCEED, default_action="x"
        )

        assert any("at most 7 days" in p for p in open_state_problems(long_wait, NOW))

    def test_the_one_reask_is_spent_after_it_is_used(self):
        fresh = _asking(NoReplyPlan.ASK_AGAIN, reasks_used=MAX_REASKS - 1)
        spent = _asking(NoReplyPlan.ASK_AGAIN, reasks_used=MAX_REASKS)

        assert open_state_problems(fresh, NOW) == []
        assert open_state_problems(spent, NOW) == [
            "if_no_reply='ask_again' is not available: this todo already used its one re-ask. "
            "Pick 'proceed' with a default_action, or 'hold'."
        ]

    def test_a_hold_that_has_started_may_check_back_monthly(self):
        holding = _waiting(
            WaitingOn.USER,
            30,
            question="q",
            if_no_reply=NoReplyPlan.HOLD,
            hold_checks=1,
        )
        first = holding.model_copy(update={"hold_checks": 0})

        assert open_state_problems(holding, NOW) == []
        assert open_state_problems(first, NOW)
        assert next_check_limit(holding) > next_check_limit(first)


class TestWhyAScheduledRunWoke:
    @pytest.mark.parametrize(
        ("todo", "reason"),
        [
            (_todo(), WakeReason.SCHEDULED_CHECK),
            (_waiting(WaitingOn.TIME), WakeReason.SCHEDULED_CHECK),
            (_waiting(WaitingOn.EVENT), WakeReason.BACKUP_CHECK),
            (_waiting(WaitingOn.SUB_TODOS), WakeReason.SUB_TODO_CHECK),
            (_waiting(WaitingOn.UNPLANNED), WakeReason.PLAN_IT),
            (_asking(NoReplyPlan.ASK_AGAIN), WakeReason.REASK_DUE),
            (_asking(NoReplyPlan.PROCEED), WakeReason.DEFAULT_DUE),
            (_asking(NoReplyPlan.HOLD, hold_checks=1), WakeReason.HOLD_CHECK),
            (_asking(NoReplyPlan.HOLD, hold_checks=MAX_HOLD_CHECKS), WakeReason.HOLD_CHECK),
            (
                _asking(NoReplyPlan.HOLD, hold_checks=MAX_HOLD_CHECKS + 1),
                WakeReason.HOLD_LAST_CHECK,
            ),
            (_asking(None), WakeReason.QUESTION_EXPIRED),
        ],
    )
    def test_the_reason_follows_the_open_state(self, todo, reason):
        assert wake_reason(todo) is reason


class TestTheBudgetAnExpiryCosts:
    def test_the_one_reask_is_spent_when_its_question_expires(self):
        assert wake_budget_update(_asking(NoReplyPlan.ASK_AGAIN)) == TodoUpdate(reasks_used=1)

    def test_each_hold_check_is_counted_when_it_comes_due(self):
        update = wake_budget_update(_asking(NoReplyPlan.HOLD, hold_checks=1))

        assert update == TodoUpdate(hold_checks=2)

    @pytest.mark.parametrize(
        "todo",
        [
            _asking(NoReplyPlan.PROCEED),
            _waiting(WaitingOn.TIME),
            _todo(),
            _todo(recurrence="daily", scheduled_at=NOW, waiting_on=WaitingOn.USER),
            _todo(
                recurrence="daily",
                scheduled_at=NOW,
                waiting_on=WaitingOn.USER,
                if_no_reply=NoReplyPlan.ASK_AGAIN,
            ),
        ],
    )
    def test_nothing_else_spends_a_budget(self, todo):
        assert wake_budget_update(todo) is None


class TestWhatTheModelReadsAboutATodo:
    def test_each_state_reads_as_a_sentence(self):
        assert describe_open_state(_waiting(WaitingOn.TIME, 3.1), NOW) == "next check in 3d"
        assert (
            describe_open_state(_waiting(WaitingOn.EVENT, 3.1), NOW)
            == "waiting on an event, backup check in 3d"
        )
        assert (
            describe_open_state(_waiting(WaitingOn.UNPLANNED, 3.1), NOW)
            == "not planned yet, plan it in 3d"
        )
        assert "waiting on its sub-todos" in describe_open_state(_waiting(WaitingOn.SUB_TODOS), NOW)

    def test_a_question_reads_with_its_expiry_and_what_follows(self):
        text = describe_open_state(_asking(NoReplyPlan.PROCEED), NOW)

        assert text == ('waiting on the user: "Ship it?" (expires in 2d, then proceed: archive it)')

    def test_a_todo_with_no_next_step_says_so(self):
        assert describe_open_state(_todo(), NOW) == "no next step set (next run never)"

    def test_a_recurring_and_a_paused_todo_say_what_they_do(self):
        recurring = _todo(recurrence="daily", scheduled_at=NOW + timedelta(hours=5, minutes=1))
        paused = _todo(pause_reason=DeactivationReason.SUBSCRIPTION_LAPSED)

        assert describe_open_state(recurring, NOW) == "repeats daily, next run in 5h"
        assert describe_open_state(paused, NOW) == "paused by the system"

    @pytest.mark.parametrize(
        ("ahead", "when"),
        [
            (timedelta(minutes=-1), "due now"),
            (timedelta(0), "due now"),
            (timedelta(seconds=30), "in 1m"),
            (timedelta(minutes=5, seconds=30), "in 5m"),
            (timedelta(minutes=59), "in 59m"),
            (timedelta(hours=1), "in 1h"),
            (timedelta(minutes=90), "in 1h"),
            (timedelta(hours=5), "in 5h"),
            (timedelta(hours=5, minutes=30), "in 5h"),
            (timedelta(days=1), "in 1d"),
            (timedelta(hours=36), "in 1d"),
        ],
    )
    def test_the_next_check_reads_in_the_largest_whole_unit(self, ahead, when):
        todo = _todo(waiting_on=WaitingOn.TIME, scheduled_at=NOW + ahead)

        assert describe_open_state(todo, NOW) == f"next check {when}"

    @pytest.mark.parametrize(
        ("plan", "words"),
        [
            (NoReplyPlan.ASK_AGAIN, "ask once more"),
            (NoReplyPlan.HOLD, "hold until they answer"),
            (NoReplyPlan.PROCEED, "proceed: archive it"),
            (None, "nothing decided"),
        ],
    )
    def test_the_plan_for_no_reply_in_words(self, plan, words):
        assert no_reply_plan_words(_asking(plan)) == words
