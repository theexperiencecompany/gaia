"""Unit tests for what a finished scheduled run of a one-time tracked todo leaves to do."""

from datetime import UTC, datetime, timedelta

import pytest

from app.constants.todos import MAX_HOLD_CHECKS, NoReplyPlan, WaitingOn
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import TodoDocument
from app.workers.tasks.todo_run_settle import Settlement, settle

CHECK = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _woke(**fields: object) -> TodoDocument:
    base: dict[str, object] = {
        "id": "t1",
        "user_id": "u1",
        "title": "t",
        "scheduled_at": CHECK,
        "waiting_on": WaitingOn.TIME,
    }
    base.update(fields)
    return TodoDocument(**base)


class TestWhatAFinishedRunLeavesToDo:
    def test_a_run_that_changed_nothing_is_parked_so_the_todo_is_never_asleep(self):
        woke = _woke()

        assert settle(woke, woke.model_copy()) is Settlement.PARK_AS_UNPLANNED

    def test_a_run_that_moved_the_next_check_stands(self):
        woke = _woke()
        moved = woke.model_copy(update={"scheduled_at": CHECK + timedelta(days=3)})

        assert settle(woke, moved) is Settlement.NOTHING

    def test_a_run_that_cleared_the_check_without_a_new_one_stands_too(self):
        """The compare-and-set write decides it; settle only reads that the check is not the one spent."""
        woke = _woke()

        assert settle(woke, woke.model_copy(update={"scheduled_at": None})) is Settlement.NOTHING

    def test_a_run_that_closed_the_todo_stands(self):
        woke = _woke()

        assert settle(woke, woke.model_copy(update={"completed": True})) is Settlement.NOTHING

    def test_a_deleted_todo_needs_nothing(self):
        assert settle(_woke(), None) is Settlement.NOTHING

    def test_a_todo_paused_meanwhile_just_ends_the_spent_check(self):
        """Resuming re-arms a paused todo, so parking it would schedule it twice."""
        woke = _woke()
        paused = woke.model_copy(update={"pause_reason": DeactivationReason.SUBSCRIPTION_LAPSED})

        assert settle(woke, paused) is Settlement.END_CHECK

    def test_a_hold_that_spent_every_check_closes_the_todo(self):
        held = _woke(
            waiting_on=WaitingOn.USER,
            question="Ship it?",
            if_no_reply=NoReplyPlan.HOLD,
            hold_checks=MAX_HOLD_CHECKS,
        )

        assert settle(held, held.model_copy()) is Settlement.CLOSE_UNANSWERED

    @pytest.mark.parametrize("checks", range(MAX_HOLD_CHECKS))
    def test_a_hold_with_checks_left_is_parked_not_closed(self, checks):
        held = _woke(
            waiting_on=WaitingOn.USER,
            question="Ship it?",
            if_no_reply=NoReplyPlan.HOLD,
            hold_checks=checks,
        )

        assert settle(held, held.model_copy()) is Settlement.PARK_AS_UNPLANNED

    def test_a_spent_ask_again_is_not_closed_by_the_hold_rule(self):
        asked = _woke(
            waiting_on=WaitingOn.USER,
            question="Ship it?",
            if_no_reply=NoReplyPlan.ASK_AGAIN,
            hold_checks=MAX_HOLD_CHECKS,
        )

        assert settle(asked, asked.model_copy()) is Settlement.PARK_AS_UNPLANNED
