"""The executor's declared outcome is believed only when this run's tool calls back it."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core.outcome_review import review_outcome, review_run
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
