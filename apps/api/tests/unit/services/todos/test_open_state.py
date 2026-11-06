"""Unit tests for the open-state rule: what an open tracked todo must say about its next step."""

from datetime import UTC, datetime, timedelta

import pytest

from app.constants.todos import (
    MAX_HOLD_CHECKS,
    MAX_REASKS,
    NoReplyPlan,
    WaitingOn,
    WakeReason,
)
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.todos.errors import OpenStateError
from app.services.todos.open_state import (
    describe_open_state,
    next_check_limit,
    no_reply_plan_words,
    open_state_problems,
    require_open_state,
    state_after,
    touches_open_state,
    wake_budget_update,
    wake_reason,
    with_waiting_normalized,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


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

        assert any("waiting_on is missing" in p for p in problems)
        assert any("scheduled_at is missing" in p for p in problems)

    def test_the_waiting_on_message_lists_every_option_so_the_model_can_pick(self):
        (message, _) = open_state_problems(_todo(), NOW)

        for option in ("'time'", "'event'", "'user'", "'sub_todos'", "'unplanned'"):
            assert option in message

    def test_a_check_in_the_past_is_refused(self):
        todo = _todo(waiting_on=WaitingOn.TIME, scheduled_at=NOW - timedelta(minutes=1))

        assert any("in the past" in p for p in open_state_problems(todo, NOW))

    def test_a_check_exactly_at_the_limit_is_valid_and_one_day_past_it_is_not(self):
        assert open_state_problems(_waiting(WaitingOn.TIME, 14), NOW) == []
        problems = open_state_problems(_waiting(WaitingOn.TIME, 15), NOW)

        assert any("at most 14 days" in p for p in problems)

    def test_a_long_wait_is_explained_as_fine_if_the_todo_looks_again(self):
        (problem,) = open_state_problems(_waiting(WaitingOn.EVENT, 60), NOW)

        assert "A longer wait is fine" in problem

    def test_a_recurring_todo_needs_only_its_schedule(self):
        assert open_state_problems(_todo(recurrence="daily", scheduled_at=NOW), NOW) == []
        assert open_state_problems(_todo(recurrence="daily"), NOW)

    def test_a_closed_or_paused_todo_has_nothing_to_wake_for(self):
        assert open_state_problems(_todo(completed=True), NOW) == []
        paused = _todo(pause_reason=DeactivationReason.SUBSCRIPTION_LAPSED)
        assert open_state_problems(paused, NOW) == []

    def test_require_open_state_raises_with_every_problem(self):
        with pytest.raises(OpenStateError) as refused:
            require_open_state(_todo(), NOW)

        assert len(refused.value.problems) == 2


class TestAQuestionToTheUser:
    def test_it_needs_the_question_and_the_plan_for_no_reply(self):
        problems = open_state_problems(_waiting(WaitingOn.USER, 2), NOW)

        assert any("needs question" in p for p in problems)
        assert any("needs if_no_reply" in p for p in problems)

    def test_proceed_needs_the_default_it_will_carry_out(self):
        todo = _waiting(WaitingOn.USER, 2, question="q", if_no_reply=NoReplyPlan.PROCEED)

        assert any("needs default_action" in p for p in open_state_problems(todo, NOW))

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
        (problem,) = open_state_problems(spent, NOW)
        assert "already used its one re-ask" in problem
        assert "'proceed'" in problem and "'hold'" in problem

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


class TestChangingWhatATodoWaitsFor:
    def test_leaving_the_user_clears_the_question_and_its_plan(self):
        existing = _asking(NoReplyPlan.HOLD, hold_checks=2)
        update = TodoUpdate(waiting_on=WaitingOn.TIME)

        normalized = with_waiting_normalized(existing, update)

        assert normalized.question is None
        assert normalized.if_no_reply is None
        assert normalized.default_action is None
        assert normalized.hold_checks == 0
        assert normalized.waiting_on is WaitingOn.TIME

    def test_a_new_question_restarts_the_hold_count(self):
        existing = _asking(NoReplyPlan.HOLD, hold_checks=2)
        update = TodoUpdate(question="A different question?")

        assert with_waiting_normalized(existing, update).hold_checks == 0

    def test_the_same_question_again_keeps_its_hold_count(self):
        existing = _asking(NoReplyPlan.HOLD, hold_checks=2)
        update = TodoUpdate(question="Ship it?")

        assert with_waiting_normalized(existing, update).model_fields_set == {"question"}

    def test_an_update_touching_neither_is_returned_untouched(self):
        update = TodoUpdate(priority=None, notify_on_run=False)

        assert with_waiting_normalized(_todo(), update) is update

    def test_state_after_applies_only_the_fields_the_update_set(self):
        existing = _waiting(WaitingOn.TIME)
        after = state_after(existing, TodoUpdate(scheduled_at=None))

        assert after.scheduled_at is None
        assert after.waiting_on is WaitingOn.TIME

    @pytest.mark.parametrize(
        ("update", "touches"),
        [
            (TodoUpdate(scheduled_at=NOW), True),
            (TodoUpdate(recurrence=None), True),
            (TodoUpdate(waiting_on=WaitingOn.TIME), True),
            (TodoUpdate(question="q"), True),
            (TodoUpdate(notify_on_run=False), False),
            (TodoUpdate(labels=["gaia-tracked"]), False),
            (TodoUpdate(expires_at=NOW), False),
        ],
    )
    def test_only_the_fields_that_decide_the_next_step_are_checked(self, update, touches):
        assert touches_open_state(update) is touches


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
