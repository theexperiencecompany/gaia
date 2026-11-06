"""The executor's declared outcome is believed only when this run's tool calls back it."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core.outcome_review import review_outcome, review_run, todo_left_asleep
from app.agents.prompts import todo_prompts
from app.agents.prompts.todo_prompts import TODO_REARM_BRIEF
from app.constants.agents import OutcomeState
from app.constants.general import FINISH_TASK_NAME

pytestmark = pytest.mark.unit


def _call(
    name: str, args: dict[str, Any], call_id: str, *, error: bool = False
) -> list[AnyMessage]:
    return [
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}]),
        ToolMessage(
            content="boom" if error else "ok",
            tool_call_id=call_id,
            name=name,
            status="error" if error else "success",
        ),
    ]


def _finish(outcome: str | None) -> list[AnyMessage]:
    args: dict[str, Any] = {"result": "report"}
    if outcome is not None:
        args["outcome"] = outcome
    return _call(FINISH_TASK_NAME, args, "finish")


def _task() -> HumanMessage:
    return HumanMessage(content="remind me friday about the visa documents")


class TestReviewOutcome:
    def test_no_declared_outcome_is_never_verified(self) -> None:
        review = review_outcome([_task(), *_call("create_todo", {}, "c1"), *_finish(None)])

        assert review.declared is None
        assert not review.verified

    def test_done_backed_by_a_successful_call_is_verified(self) -> None:
        review = review_outcome([_task(), *_call("create_todo", {}, "c1"), *_finish("done")])

        assert review.declared is OutcomeState.DONE
        assert review.verified

    def test_done_with_only_a_failed_call_is_not_verified(self) -> None:
        review = review_outcome(
            [_task(), *_call("create_todo", {}, "c1", error=True), *_finish("done")]
        )

        assert review.problem is not None

    def test_done_with_only_discovery_is_not_verified(self) -> None:
        review = review_outcome([_task(), *_call("retrieve_tools", {}, "c1"), *_finish("done")])

        assert review.problem is not None

    def test_a_reminder_does_not_back_schedule(self) -> None:
        """A reminder pings the user and never wakes GAIA, so it cannot be GAIA's follow-up."""
        review = review_outcome(
            [_task(), *_call("create_reminder_tool", {"payload": {}}, "c1"), *_finish("schedule")]
        )

        assert review.problem is not None

    def test_a_reminder_backs_done_for_a_plain_remind_me(self) -> None:
        review = review_outcome(
            [_task(), *_call("create_reminder_tool", {"payload": {}}, "c1"), *_finish("done")]
        )

        assert review.verified

    def test_schedule_backed_by_a_scheduled_tracked_todo_is_verified(self) -> None:
        review = review_outcome(
            [
                _task(),
                *_call(
                    "create_tracked_todo", {"title": "visa", "scheduled_at": "2026-10-30"}, "c1"
                ),
                *_finish("schedule"),
            ]
        )

        assert review.verified

    def test_a_tracked_todo_with_only_a_due_date_does_not_back_schedule(self) -> None:
        """Seen live: a due_date-only tracked todo for 'make sure I don't forget' never wakes."""
        review = review_outcome(
            [
                _task(),
                *_call("create_tracked_todo", {"title": "tax", "due_date": "2026-11-20"}, "c1"),
                *_finish("schedule"),
            ]
        )

        assert review.problem is not None

    def test_schedule_through_the_execute_proxy_is_seen(self) -> None:
        review = review_outcome(
            [
                _task(),
                *_call(
                    "execute",
                    {"tool_name": "create_tracked_todo", "data": {"recurrence": "weekly"}},
                    "c1",
                ),
                *_finish("schedule"),
            ]
        )

        assert review.verified

    def test_subscribe_needs_a_trigger_watch(self) -> None:
        unbacked = review_outcome(
            [_task(), *_call("create_tracked_todo", {}, "c1"), *_finish("subscribe")]
        )
        backed = review_outcome(
            [_task(), *_call("subscribe_todo_to_trigger", {}, "c1"), *_finish("subscribe")]
        )

        assert unbacked.problem is not None
        assert backed.verified

    @pytest.mark.parametrize("outcome", ["ask", "blocked"])
    def test_ask_and_blocked_need_no_work(self, outcome: str) -> None:
        assert review_outcome([_task(), *_finish(outcome)]).verified

    def test_an_unknown_outcome_counts_as_undeclared(self) -> None:
        assert review_outcome([_task(), *_finish("finished")]).declared is None


class TestReviewRun:
    def test_a_previous_delegation_s_work_does_not_back_this_one(self) -> None:
        thread: list[AnyMessage] = [
            HumanMessage(content="first task"),
            *_call("create_tracked_todo", {"scheduled_at": "2026-10-30"}, "c1"),
            AIMessage(content="first done"),
            HumanMessage(content="second task"),
            *_finish("schedule"),
        ]

        assert not review_run(thread).verified


class TestATodoIsNeverLeftAsleep:
    """Seen in real use: tracked todos run once with no next check stayed open forever.

    Creating one without a next step is refused in code, so only a run that spent its
    scheduled check can leave a todo asleep.
    """

    BRIEFED = HumanMessage(content=f"Execute the scheduled task: ship it\n\n{TODO_REARM_BRIEF}")

    def test_a_run_that_only_reads_must_close_or_rearm_the_todo(self) -> None:
        asleep = [self.BRIEFED, *_call("read", {"path": "canvas.md"}, "c1"), *_finish("ask")]

        assert todo_left_asleep(asleep) is not None
        assert not review_outcome(asleep).verified

    @pytest.mark.parametrize(
        "ending",
        [
            ("update_tracked_todo", {"todo_id": "t", "scheduled_at": "3d", "waiting_on": "time"}),
            ("update_tracked_todo", {"todo_id": "t", "recurrence": "daily"}),
            ("complete_tracked_todo", {"todo_id": "t", "summary": "done"}),
        ],
    )
    def test_closing_it_or_setting_its_next_check_ends_the_run_cleanly(
        self, ending: tuple[str, dict[str, Any]]
    ) -> None:
        name, args = ending
        delegation = [self.BRIEFED, *_call(name, args, "c1"), *_finish("ask")]

        assert todo_left_asleep(delegation) is None

    @pytest.mark.parametrize(
        "not_a_next_check",
        [
            ("subscribe_todo_to_trigger", {"todo_id": "t", "trigger_name": "x"}),
            ("bash", {"command": "run", "run_todo_id": "t"}),
            ("update_tracked_todo", {"todo_id": "t", "priority": "high"}),
        ],
    )
    def test_a_watch_or_an_unrelated_edit_is_not_a_next_check(
        self, not_a_next_check: tuple[str, dict[str, Any]]
    ) -> None:
        """The watch wakes the todo early, but the backup check this run spent is still owed."""
        name, args = not_a_next_check
        delegation = [self.BRIEFED, *_call(name, args, "c1"), *_finish("ask")]

        assert todo_left_asleep(delegation) is not None

    def test_a_failed_next_check_does_not_count(self) -> None:
        delegation = [
            self.BRIEFED,
            *_call("update_tracked_todo", {"todo_id": "t", "scheduled_at": "3d"}, "c1", error=True),
            *_finish("ask"),
        ]

        assert todo_left_asleep(delegation) is not None

    def test_an_unbriefed_run_is_never_flagged(self) -> None:
        """Creating a todo with no next step is refused by the tool itself, not judged here."""
        assert todo_left_asleep([_task(), *_call("create_todo", {}, "c1")]) is None
        assert (
            todo_left_asleep([_task(), *_call("create_tracked_todo", {"title": "t"}, "c1")]) is None
        )

    def test_a_plain_text_ending_that_strands_a_todo_still_reports_why(self) -> None:
        review = review_outcome([self.BRIEFED, *_call("read", {"path": "canvas.md"}, "c1")])

        assert review.declared is None
        assert review.problem is not None


def _wakes_again_task() -> HumanMessage:
    return HumanMessage(
        content=f"Execute the scheduled task: call mom\n\n{todo_prompts.TODO_WAKES_AGAIN_BRIEF}"
    )


class TestARunOfATodoThatWakesAgain:
    """Seen live: an hourly 'keep after me' todo's own run sent the same reminder twice.

    Its recurrence already wakes GAIA, so schedule was rejected as unbacked, the
    completion nudge sent the run back, and it reminded the user again.
    """

    def test_schedule_is_backed_by_the_wake_the_todo_already_has(self) -> None:
        review = review_outcome(
            [
                _wakes_again_task(),
                *_call("send_notification", {"title": "Call mom"}, "c1"),
                *_finish("schedule"),
            ]
        )

        assert review.verified

    def test_done_still_needs_a_work_call(self) -> None:
        assert not review_outcome([_wakes_again_task(), *_finish("done")]).verified

    def test_an_unbriefed_run_still_needs_a_tracked_todo_for_schedule(self) -> None:
        review = review_outcome(
            [
                _task(),
                *_call("send_notification", {"title": "Call mom"}, "c1"),
                *_finish("schedule"),
            ]
        )

        assert review.problem is not None
