"""The executor's declared outcome is believed only when this run's tool calls back it."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core.outcome_review import review_outcome, review_run, todo_left_asleep
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
    """Seen in real use: tracked todos created or run once with nothing to wake them stayed open forever."""

    def test_a_todo_created_with_nothing_to_wake_it_is_flagged(self) -> None:
        delegation = [
            _task(),
            *_call("create_tracked_todo", {"title": "hidden per-todo chat"}, "c1"),
            *_finish("done"),
        ]

        assert todo_left_asleep(delegation) is not None
        assert not review_outcome(delegation).verified

    @pytest.mark.parametrize(
        "arming",
        [
            ("subscribe_todo_to_trigger", {"todo_id": "t1", "trigger_name": "x"}),
            ("update_tracked_todo", {"todo_id": "t1", "scheduled_at": "2026-11-03T09:00:00"}),
            ("complete_tracked_todo", {"todo_id": "t1", "summary": "done"}),
            ("bash", {"command": "run", "run_todo_id": "t1"}),
        ],
    )
    def test_a_later_watch_schedule_completion_or_bound_run_arms_it(
        self, arming: tuple[str, dict[str, Any]]
    ) -> None:
        name, args = arming
        delegation = [
            _task(),
            *_call("create_tracked_todo", {"title": "t"}, "c1"),
            *_call(name, args, "c2"),
        ]

        assert todo_left_asleep(delegation) is None

    @pytest.mark.parametrize("key", ["scheduled_at", "recurrence", "gmail_thread_id"])
    def test_a_todo_created_waking_on_its_own_is_fine(self, key: str) -> None:
        delegation = [_task(), *_call("create_tracked_todo", {"title": "t", key: "x"}, "c1")]

        assert todo_left_asleep(delegation) is None

    def test_a_failed_arming_call_does_not_count(self) -> None:
        delegation = [
            _task(),
            *_call("create_tracked_todo", {"title": "t"}, "c1"),
            *_call("subscribe_todo_to_trigger", {"todo_id": "t1"}, "c2", error=True),
        ]

        assert todo_left_asleep(delegation) is not None

    def test_two_unarmed_todos_need_two_arming_calls(self) -> None:
        delegation = [
            _task(),
            *_call("create_tracked_todo", {"title": "a"}, "c1"),
            *_call("create_tracked_todo", {"title": "b"}, "c2"),
            *_call("subscribe_todo_to_trigger", {"todo_id": "a"}, "c3"),
        ]

        assert todo_left_asleep(delegation) is not None

    def test_a_run_briefed_as_the_todo_s_last_look_must_close_or_rearm_it(self) -> None:
        briefed = HumanMessage(content=f"Execute the scheduled task: ship it\n\n{TODO_REARM_BRIEF}")

        asleep = [briefed, *_call("read", {"path": "canvas.md"}, "c1"), *_finish("ask")]
        rearmed = [
            briefed,
            *_call("update_tracked_todo", {"todo_id": "t", "scheduled_at": "2026-11-10"}, "c1"),
            *_finish("ask"),
        ]

        assert todo_left_asleep(asleep) is not None
        assert todo_left_asleep(rearmed) is None

    def test_an_unbriefed_run_that_creates_nothing_is_not_flagged(self) -> None:
        assert todo_left_asleep([_task(), *_call("create_todo", {}, "c1")]) is None

    def test_a_plain_text_ending_that_strands_a_todo_still_reports_why(self) -> None:
        review = review_outcome([_task(), *_call("create_tracked_todo", {"title": "t"}, "c1")])

        assert review.declared is None
        assert review.problem is not None
