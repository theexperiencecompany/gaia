"""The executor's declared outcome is believed only when this run's tool calls back it."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core import outcome_review
from app.agents.core.outcome_review import (
    OutcomeReview,
    review_outcome,
    review_run,
    todo_left_asleep,
)
from app.agents.prompts import todo_prompts
from app.agents.prompts.todo_prompts import TODO_REARM_BRIEF
from app.constants.agents import NO_REPORT_PROBLEM, OutcomeState
from app.constants.general import FINISH_TASK_NAME
from app.core.lazy_loader import providers

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


def _finish(outcome: str | None, **report: Any) -> list[AnyMessage]:
    args: dict[str, Any] = {"result": "report", **report}
    if outcome is not None:
        args["outcome"] = outcome
    return _call(FINISH_TASK_NAME, args, "finish")


def _reads_only(tool_name: str) -> bool:
    return False


def _writes_everything(tool_name: str) -> bool:
    return True


def _review(
    delegation: list[AnyMessage], is_write: Callable[[str], bool] = _reads_only
) -> OutcomeReview:
    return review_outcome(delegation, is_write)


#: The problem a run that spent its todo's check without setting another is fed back.
LEFT_ASLEEP = "the todo was left open with no next check, so nothing will look at it again"


def _task() -> HumanMessage:
    return HumanMessage(content="remind me friday about the visa documents")


class TestReviewOutcome:
    def test_no_declared_outcome_is_never_verified(self) -> None:
        review = _review([_task(), *_call("create_todo", {}, "c1"), *_finish(None)])

        assert review.declared is None
        assert not review.verified

    def test_done_backed_by_a_successful_call_is_verified(self) -> None:
        review = _review([_task(), *_call("create_todo", {}, "c1"), *_finish("done")])

        assert review.declared is OutcomeState.DONE
        assert review.verified

    def test_done_with_only_a_failed_call_is_not_verified(self) -> None:
        review = _review([_task(), *_call("create_todo", {}, "c1", error=True), *_finish("done")])

        assert review == OutcomeReview(
            OutcomeState.DONE, "done was declared but no work call succeeded"
        )

    def test_done_with_only_discovery_is_not_verified(self) -> None:
        review = _review([_task(), *_call("retrieve_tools", {}, "c1"), *_finish("done")])

        assert review == OutcomeReview(
            OutcomeState.DONE, "done was declared but no work call succeeded"
        )

    def test_a_reminder_does_not_back_schedule(self) -> None:
        """A reminder pings the user and never wakes GAIA, so it cannot be GAIA's follow-up."""
        review = _review(
            [_task(), *_call("create_reminder_tool", {"payload": {}}, "c1"), *_finish("schedule")]
        )

        assert review == OutcomeReview(
            OutcomeState.SCHEDULE,
            "schedule was declared but no tracked todo was scheduled to wake GAIA",
        )

    def test_a_reminder_backs_done_for_a_plain_remind_me(self) -> None:
        review = _review(
            [_task(), *_call("create_reminder_tool", {"payload": {}}, "c1"), *_finish("done")]
        )

        assert review.verified

    def test_schedule_backed_by_a_scheduled_tracked_todo_is_verified(self) -> None:
        review = _review(
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
        review = _review(
            [
                _task(),
                *_call("create_tracked_todo", {"title": "tax", "due_date": "2026-11-20"}, "c1"),
                *_finish("schedule"),
            ]
        )

        assert review.problem is not None

    def test_schedule_through_the_execute_proxy_is_seen(self) -> None:
        review = _review(
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

    def test_a_schedule_sent_as_json_text_through_the_execute_proxy_is_seen(self) -> None:
        """Execute's data can arrive JSON-encoded; reviewing it once raised and lost the result."""
        review = _review(
            [
                _task(),
                *_call(
                    "execute",
                    {"tool_name": "create_tracked_todo", "data": '{"recurrence": "weekly"}'},
                    "c1",
                ),
                *_finish("schedule"),
            ]
        )

        assert review.verified

    def test_subscribe_needs_a_trigger_watch(self) -> None:
        unbacked = _review(
            [_task(), *_call("create_tracked_todo", {}, "c1"), *_finish("subscribe")]
        )
        backed = _review(
            [_task(), *_call("subscribe_todo_to_trigger", {}, "c1"), *_finish("subscribe")]
        )

        assert unbacked == OutcomeReview(
            OutcomeState.SUBSCRIBE, "subscribe was declared but no trigger watch was set"
        )
        assert backed.verified

    @pytest.mark.parametrize("outcome", ["needs_you", "blocked"])
    def test_needs_you_and_blocked_need_no_work(self, outcome: str) -> None:
        assert _review([_task(), *_finish(outcome)]).verified

    def test_an_unknown_outcome_is_not_a_declaration(self) -> None:
        review = _review([_task(), *_finish("finished")])

        assert review.declared is None
        assert not review.verified


class TestReviewRun:
    def test_a_previous_delegation_s_work_does_not_back_this_one(self) -> None:
        thread: list[AnyMessage] = [
            HumanMessage(content="first task"),
            *_call("create_tracked_todo", {"scheduled_at": "2026-10-30"}, "c1"),
            AIMessage(content="first done"),
            HumanMessage(content="second task"),
            *_finish("schedule"),
        ]

        assert not review_run(thread, _reads_only).verified


class TestATodoIsNeverLeftAsleep:
    """Seen in real use: tracked todos run once with no next check stayed open forever.

    Creating one without a next step is refused in code, so only a run that spent its
    scheduled check can leave a todo asleep.
    """

    BRIEFED = HumanMessage(content=f"Execute the scheduled task: ship it\n\n{TODO_REARM_BRIEF}")

    def test_a_run_that_only_reads_must_close_or_rearm_the_todo(self) -> None:
        asleep = [self.BRIEFED, *_call("read", {"path": "canvas.md"}, "c1"), *_finish("needs_you")]

        assert _review(asleep) == OutcomeReview(OutcomeState.NEEDS_YOU, LEFT_ASLEEP)

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
        delegation = [self.BRIEFED, *_call(name, args, "c1"), *_finish("needs_you")]

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
        delegation = [self.BRIEFED, *_call(name, args, "c1"), *_finish("needs_you")]

        assert todo_left_asleep(delegation) is not None

    def test_a_failed_next_check_does_not_count(self) -> None:
        delegation = [
            self.BRIEFED,
            *_call("update_tracked_todo", {"todo_id": "t", "scheduled_at": "3d"}, "c1", error=True),
            *_finish("needs_you"),
        ]

        assert todo_left_asleep(delegation) is not None

    def test_a_delegation_that_does_not_open_with_its_task_is_never_flagged(self) -> None:
        assert todo_left_asleep([*_call("read", {"path": "canvas.md"}, "c1")]) is None
        assert todo_left_asleep([]) is None

    def test_an_unbriefed_run_is_never_flagged(self) -> None:
        """Creating a todo with no next step is refused by the tool itself, not judged here."""
        assert todo_left_asleep([_task(), *_call("create_todo", {}, "c1")]) is None
        assert (
            todo_left_asleep([_task(), *_call("create_tracked_todo", {"title": "t"}, "c1")]) is None
        )

    def test_a_plain_text_ending_that_strands_a_todo_still_reports_why(self) -> None:
        review = _review([self.BRIEFED, *_call("read", {"path": "canvas.md"}, "c1")])

        assert review == OutcomeReview(None, LEFT_ASLEEP)


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
        review = _review(
            [
                _wakes_again_task(),
                *_call("send_notification", {"title": "Call mom"}, "c1"),
                *_finish("schedule"),
            ]
        )

        assert review.verified

    def test_done_still_needs_a_work_call(self) -> None:
        assert not _review([_wakes_again_task(), *_finish("done")]).verified

    def test_an_unbriefed_run_still_needs_a_tracked_todo_for_schedule(self) -> None:
        review = _review(
            [
                _task(),
                *_call("send_notification", {"title": "Call mom"}, "c1"),
                *_finish("schedule"),
            ]
        )

        assert review.problem is not None


class TestAnAbsentReportIsUnverified:
    """A run that ends without a finish_task report is never success, whatever its last words say."""

    def test_a_plain_text_stop_after_work_is_not_verified(self) -> None:
        review = _review(
            [_task(), *_call("create_todo", {}, "c1"), AIMessage(content="Task completed")]
        )

        assert review == OutcomeReview(None, NO_REPORT_PROBLEM)

    def test_a_finish_without_an_outcome_is_not_verified(self) -> None:
        review = _review([_task(), *_call("create_todo", {}, "c1"), *_finish(None)])

        assert review == OutcomeReview(None, NO_REPORT_PROBLEM)

    def test_a_finish_whose_report_breaks_its_schema_is_not_verified(self) -> None:
        review = _review(
            [_task(), *_finish("done", facts=[{"text": "sent it", "kind": "guessed"}])]
        )

        assert review.declared is None
        assert review.problem is not None
        assert "finish_task" in review.problem


def _fact(kind: str, *call_ids: str, text: str = "a fact") -> dict[str, Any]:
    return {"text": text, "kind": kind, "source_call_ids": list(call_ids)}


def _problem(delegation: list[AnyMessage], is_write: Callable[[str], bool] = _reads_only) -> str:
    problem = _review(delegation, is_write).problem
    assert problem is not None, "the review accepted a report it should have refused"
    return problem


_SCOPE = {"covered": "the inbox", "complete": True, "gaps": []}
_FAIL = {"reason": "provider_error", "recovery": "user_can_rerun"}


class TestDidFactsNeedASuccessfulCall:
    def test_a_did_citing_only_a_call_that_errored_is_refused(self) -> None:
        problem = _problem(
            [
                _task(),
                *_call("send_email", {}, "c1", error=True),
                *_finish("partial", facts=[_fact("did", "c1")]),
            ],
            _writes_everything,
        )

        assert "c1" in problem
        assert "errored" in problem

    def test_a_did_with_no_call_behind_it_is_refused(self) -> None:
        problem = _problem(
            [_task(), *_call("create_todo", {}, "c1"), *_finish("done", facts=[_fact("did")])]
        )

        assert "did" in problem

    def test_a_did_citing_a_successful_call_passes(self) -> None:
        review = _review(
            [_task(), *_call("send_email", {}, "c1"), *_finish("done", facts=[_fact("did", "c1")])],
            _writes_everything,
        )

        assert review.verified

    def test_a_did_citing_one_error_and_one_success_passes(self) -> None:
        review = _review(
            [
                _task(),
                *_call("send_email", {}, "c1", error=True),
                *_call("send_email", {}, "c2"),
                *_finish("done", facts=[_fact("did", "c1", "c2")]),
            ],
            _writes_everything,
        )

        assert review.verified

    def test_a_call_whose_result_says_it_failed_is_not_a_success(self) -> None:
        failed_body: list[AnyMessage] = [
            AIMessage(content="", tool_calls=[{"name": "send_email", "args": {}, "id": "c1"}]),
            ToolMessage(
                content='{"success": false, "error": "bounced"}',
                tool_call_id="c1",
                name="send_email",
            ),
        ]

        problem = _problem(
            [_task(), *failed_body, *_finish("partial", facts=[_fact("did", "c1")])],
            _writes_everything,
        )

        assert "errored" in problem


class TestCitedCallsMustExist:
    def test_an_id_this_run_never_made_is_refused(self) -> None:
        problem = _problem(
            [_task(), *_call("lookup", {}, "c1"), *_finish("done", facts=[_fact("observed", "c9")])]
        )

        assert "c9" in problem

    def test_ids_of_calls_that_ran_pass(self) -> None:
        review = _review(
            [
                _task(),
                *_call("lookup", {}, "c1"),
                *_finish("done", facts=[_fact("observed", "c1")], scope=_SCOPE),
            ]
        )

        assert review.verified


class TestEverySuccessfulWriteIsAccountedFor:
    def test_an_unreported_write_is_refused_naming_it(self) -> None:
        problem = _problem(
            [_task(), *_call("send_email", {}, "c1"), *_finish("done", facts=[])],
            _writes_everything,
        )

        assert "send_email" in problem
        assert "c1" in problem

    def test_an_observed_fact_does_not_account_for_a_write(self) -> None:
        problem = _problem(
            [
                _task(),
                *_call("send_email", {}, "c1"),
                *_finish("done", facts=[_fact("observed", "c1")], scope=_SCOPE),
            ],
            _writes_everything,
        )

        assert "c1" in problem

    @pytest.mark.parametrize("kind", ["did", "pending_confirmation", "not_done"])
    def test_did_pending_and_not_done_account_for_a_write(self, kind: str) -> None:
        outcome = "done" if kind == "did" else "partial"
        review = _review(
            [_task(), *_call("send_email", {}, "c1"), *_finish(outcome, facts=[_fact(kind, "c1")])],
            _writes_everything,
        )

        assert review.verified

    def test_a_read_needs_no_fact(self) -> None:
        assert _review([_task(), *_call("search", {}, "c1"), *_finish("done")]).verified

    def test_a_write_that_errored_needs_no_fact(self) -> None:
        review = _review(
            [
                _task(),
                *_call("send_email", {}, "c1", error=True),
                *_finish("failed", failure=_FAIL),
            ],
            _writes_everything,
        )

        assert review.verified

    def test_a_write_through_the_execute_proxy_is_classified_by_its_real_tool(self) -> None:
        delegation = [
            _task(),
            *_call("execute", {"tool_name": "send_email", "data": {}}, "c1"),
            *_finish("done", facts=[]),
        ]

        assert "c1" in _problem(delegation, lambda name: name == "send_email")
        assert _review(delegation, lambda name: name == "delete_event").verified


class TestAReportMustAgreeWithItself:
    @pytest.mark.parametrize("kind", ["not_done", "pending_confirmation"])
    def test_done_with_an_unfinished_deliverable_is_refused(self, kind: str) -> None:
        problem = _problem(
            [_task(), *_call("book", {}, "c1"), *_finish("done", facts=[_fact(kind, "c1")])]
        )

        assert "done" in problem
        assert kind in problem

    def test_partial_may_carry_an_unfinished_deliverable(self) -> None:
        review = _review(
            [
                _task(),
                *_call("book", {}, "c1"),
                *_finish("partial", facts=[_fact("not_done", "c1")]),
            ]
        )

        assert review.verified

    def test_failed_without_a_failure_is_refused(self) -> None:
        assert "failure" in _problem([_task(), *_finish("failed")])

    def test_failed_with_a_failure_passes(self) -> None:
        assert _review([_task(), *_finish("failed", failure=_FAIL)]).verified

    def test_nothing_new_without_scope_is_refused(self) -> None:
        assert "scope" in _problem([_task(), *_finish("nothing_new")])

    def test_nothing_new_with_scope_passes(self) -> None:
        assert _review([_task(), *_finish("nothing_new", scope=_SCOPE)]).verified

    def test_an_answer_without_scope_is_refused(self) -> None:
        problem = _problem(
            [_task(), *_call("search", {}, "c1"), *_finish("done", answer={"verdict": "true"})]
        )

        assert "scope" in problem

    @pytest.mark.parametrize("kind", ["observed", "inferred"])
    def test_a_report_of_only_findings_without_scope_is_refused(self, kind: str) -> None:
        sources = ("c1",) if kind == "observed" else ()
        problem = _problem(
            [_task(), *_call("search", {}, "c1"), *_finish("done", facts=[_fact(kind, *sources)])]
        )

        assert "scope" in problem

    def test_findings_with_scope_pass(self) -> None:
        review = _review(
            [
                _task(),
                *_call("search", {}, "c1"),
                *_finish(
                    "done",
                    facts=[_fact("observed", "c1")],
                    answer={"recommendation": "the first"},
                    scope=_SCOPE,
                ),
            ]
        )

        assert review.verified

    def test_a_report_that_also_did_something_needs_no_scope(self) -> None:
        review = _review(
            [
                _task(),
                *_call("send_email", {}, "c1"),
                *_finish("done", facts=[_fact("did", "c1"), _fact("observed", "c1")]),
            ],
            _writes_everything,
        )

        assert review.verified

    def test_a_report_with_no_facts_needs_no_scope(self) -> None:
        assert _review([_task(), *_call("create_todo", {}, "c1"), *_finish("done")]).verified


class TestRegisteredIsWrite:
    """The tool registry's destructiveness is what the report review calls a write."""

    @staticmethod
    def _registry(monkeypatch: pytest.MonkeyPatch, flag: bool | None) -> None:
        registry = SimpleNamespace(is_tool_destructive=lambda tool_name: flag)
        monkeypatch.setattr(providers, "get", lambda name: registry)

    @pytest.mark.parametrize(
        ("flag", "is_write"),
        [(True, True), (False, False), (None, True)],
        ids=["destructive", "reviewed-safe", "unclassified"],
    )
    def test_the_registry_flag_decides_and_unclassified_counts_as_a_write(
        self, monkeypatch: pytest.MonkeyPatch, flag: bool | None, is_write: bool
    ) -> None:
        self._registry(monkeypatch, flag)

        assert outcome_review.registered_is_write("send_email") is is_write

    def test_plumbing_is_never_a_write_even_when_unclassified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._registry(monkeypatch, None)

        assert outcome_review.registered_is_write("plan_tasks") is False
