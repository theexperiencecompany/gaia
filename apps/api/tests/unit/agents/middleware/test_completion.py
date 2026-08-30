"""The harness-owned completion predicates, tested directly.

``tests/integration/agents/test_harness_completion.py`` proves the graph wiring
— that ``should_continue`` routes to ``nudge_continue`` and that the nudge is
bounded. It never exercises the predicates' own boundaries, so this file does:
where the delegation boundary falls, what counts as a promise, and the exact
tool-call floor.

The delegation scoping is the load-bearing part. The executor keeps ONE thread
per conversation, so counting the whole thread let delegation two inherit
delegation one's tool calls and nudges — the guard fired once per conversation
and was dead for the rest of it.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
import pytest

from app.agents.middleware.completion import (
    completion_nudges_spent,
    current_delegation,
    playbook_decision_pending,
    playbook_nudges_spent,
    reply_promises_future_work,
    work_looks_unfinished,
)
from app.constants.agents import (
    PLAYBOOK_CHECK_TAG,
    PLAYBOOK_DECISION_NUDGE_MESSAGE,
    PLAYBOOK_DECISION_TOOL_NAMES,
)
from app.constants.general import FINISH_TASK_NAME
from app.constants.llm import (
    COMPLETION_NUDGE_MESSAGE,
    COMPLETION_PROMISE_MARKERS,
)
from tests.factories import make_state

pytestmark = pytest.mark.unit


def _task(text: str = "do the thing") -> HumanMessage:
    """The per-delegation task turn ``build_initial_messages`` appends."""
    return HumanMessage(content=text)


def _clock() -> HumanMessage:
    """The injected time-context turn — a HumanMessage that is not a task."""
    return HumanMessage(
        content="Current time: 2026-01-01", additional_kwargs={"time_context": True}
    )


def _nudge() -> HumanMessage:
    return HumanMessage(content=COMPLETION_NUDGE_MESSAGE)


def _tool_result(text: str = "result") -> ToolMessage:
    return ToolMessage(content=text, tool_call_id="call_1")


def _worked(count: int) -> list[AnyMessage]:
    """``count`` completed tool round-trips."""
    messages: list[AnyMessage] = []
    for _ in range(count):
        messages.extend([AIMessage(content=""), _tool_result()])
    return messages


class TestCurrentDelegation:
    def test_scopes_to_the_newest_task_turn(self) -> None:
        second_task = _task("second task")
        state = make_state(
            messages=[_task("first task"), *_worked(2), second_task, AIMessage(content="on it")]
        )

        delegation = current_delegation(state)

        assert delegation[0] is second_task
        assert len(delegation) == 2

    def test_the_clock_turn_is_not_a_delegation_boundary(self) -> None:
        """The time-context turn arrives as a HumanMessage after the task; treating
        it as the boundary would cut the delegation's own work out of the count."""
        task = _task()
        state = make_state(messages=[task, *_worked(2), _clock(), AIMessage(content="done")])

        delegation = current_delegation(state)

        assert delegation[0] is task

    def test_the_nudge_is_not_a_delegation_boundary(self) -> None:
        """The nudge is also a HumanMessage. If it were the boundary, the nudge it
        just spent would fall outside the window and the guard could never stop."""
        task = _task()
        state = make_state(messages=[task, *_worked(1), _nudge(), AIMessage(content="done")])

        delegation = current_delegation(state)

        assert delegation[0] is task

    def test_falls_back_to_the_whole_thread_when_no_task_turn_exists(self) -> None:
        messages = [AIMessage(content="orphan"), _tool_result()]
        state = make_state(messages=messages)

        assert current_delegation(state) == messages

    def test_finds_a_task_turn_that_is_the_last_message(self) -> None:
        """A delegation that has only just been handed over: the task turn is the
        newest message and the model has not replied yet."""
        task = _task("newest task")
        state = make_state(messages=[AIMessage(content="earlier"), _tool_result(), task])

        assert current_delegation(state) == [task]

    def test_finds_a_task_turn_at_the_very_start_of_the_thread(self) -> None:
        """The scan has to reach index 0. A thread can open with a non-task message
        (a restored summary, a system-style AI turn) before the first delegation."""
        task = _task()
        state = make_state(messages=[AIMessage(content="preamble"), task, AIMessage(content="ok")])

        delegation = current_delegation(state)

        assert delegation[0] is task
        assert len(delegation) == 2

    def test_a_skipped_turn_does_not_end_the_scan(self) -> None:
        """Skipping the clock turn must keep walking backwards to the real task. If
        the scan stopped there instead, the whole thread would be returned and the
        previous delegation's work would be counted all over again."""
        second_task = _task("second task")
        state = make_state(
            messages=[
                _task("first task"),
                AIMessage(content="finished one"),
                second_task,
                _clock(),
                AIMessage(content="working"),
            ]
        )

        delegation = current_delegation(state)

        assert delegation[0] is second_task
        assert len(delegation) == 3

    def test_empty_thread_yields_nothing(self) -> None:
        assert current_delegation(make_state(messages=[])) == []

    def test_a_state_without_a_messages_channel_yields_nothing(self) -> None:
        """The predicates run against partially-built states (the graph's own
        ``state.get`` contract), so an absent channel must read as empty rather
        than raise into the executor's routing decision."""
        assert current_delegation({}) == []

    def test_returns_a_copy_rather_than_a_live_view(self) -> None:
        messages = [_task(), AIMessage(content="hi")]
        state = make_state(messages=messages)

        current_delegation(state).append(AIMessage(content="mutated"))

        assert len(state["messages"]) == 2


class TestCompletionNudgesSpent:
    def test_counts_nudges_in_the_current_delegation(self) -> None:
        state = make_state(messages=[_task(), _nudge(), AIMessage(content="a"), _nudge()])

        assert completion_nudges_spent(state) == 2

    def test_zero_when_none_were_spent(self) -> None:
        state = make_state(messages=[_task(), *_worked(1)])

        assert completion_nudges_spent(state) == 0

    def test_a_new_delegation_does_not_inherit_the_previous_one_s_nudges(self) -> None:
        """The executor's thread outlives the delegation. Counting the thread made
        the second delegation look like it had already spent its nudge budget, so
        the guard switched itself off for every delegation after the first."""
        state = make_state(
            messages=[
                _task("first task"),
                _nudge(),
                AIMessage(content="finished one"),
                _task("second task"),
                AIMessage(content="finished two"),
            ]
        )

        assert completion_nudges_spent(state) == 0

    def test_a_lookalike_human_turn_is_not_counted_as_a_nudge(self) -> None:
        state = make_state(
            messages=[_task(), HumanMessage(content=COMPLETION_NUDGE_MESSAGE + " and more")]
        )

        assert completion_nudges_spent(state) == 0


class TestReplyPromisesFutureWork:
    @pytest.mark.parametrize("marker", COMPLETION_PROMISE_MARKERS)
    def test_every_declared_marker_is_detected(self, marker: str) -> None:
        state = make_state(messages=[_task(), AIMessage(content=f"Sure — {marker}!")])

        assert reply_promises_future_work(state) is True

    def test_matching_ignores_case(self) -> None:
        state = make_state(messages=[_task(), AIMessage(content="Hang Tight while I work")])

        assert reply_promises_future_work(state) is True

    def test_a_clean_final_answer_is_not_a_promise(self) -> None:
        state = make_state(messages=[_task(), AIMessage(content="Here is the answer: 42.")])

        assert reply_promises_future_work(state) is False

    def test_text_blocks_are_searched_too(self) -> None:
        """Multimodal replies arrive as a block list; reading only ``str`` content
        would let a promise through unnoticed."""
        state = make_state(
            messages=[_task(), AIMessage(content=[{"type": "text", "text": "hang tight"}])]
        )

        assert reply_promises_future_work(state) is True

    def test_only_the_final_message_counts(self) -> None:
        """A promise mid-run is fine — the model went on to do the work. Only the
        message the user would actually be left with matters."""
        state = make_state(
            messages=[
                _task(),
                AIMessage(content="hang tight"),
                *_worked(2),
                AIMessage(content="Here is the answer: 42."),
            ]
        )

        assert reply_promises_future_work(state) is False

    @pytest.mark.parametrize(
        "last",
        [
            pytest.param(_tool_result("Reply: hang tight, still digging"), id="tool-result"),
            pytest.param(HumanMessage(content="hang tight, I'll send it over"), id="user-turn"),
        ],
    )
    def test_a_promise_from_anyone_but_the_assistant_is_ignored(self, last: AnyMessage) -> None:
        """Only the assistant's own closing reply is a promise. A tool result that
        quotes an email saying "hang tight", or a user typing it, must not make the
        harness treat a finished run as unfinished — and the run has not ended on a
        plain-text reply in either case."""
        state = make_state(messages=[_task(), *_worked(2), last])

        assert reply_promises_future_work(state) is False

    def test_empty_thread_is_not_a_promise(self) -> None:
        assert reply_promises_future_work(make_state(messages=[])) is False


class TestWorkLooksUnfinished:
    @pytest.mark.parametrize("status", ["pending", "in_progress"])
    def test_an_open_todo_blocks_the_stop(self, status: str) -> None:
        state = make_state(
            messages=[_task(), *_worked(2), AIMessage(content="all done")],
            todos=[{"status": status}],
        )

        assert work_looks_unfinished(state) is True

    def test_completed_todos_do_not_block(self) -> None:
        state = make_state(
            messages=[_task(), *_worked(2), AIMessage(content="all done")],
            todos=[{"status": "completed"}],
        )

        assert work_looks_unfinished(state) is False

    def test_a_promise_blocks_even_when_the_work_looks_done(self) -> None:
        state = make_state(
            messages=[
                _task(),
                *_worked(2),
                AIMessage(content="hang tight"),
            ],
            todos=[],
        )

        assert work_looks_unfinished(state) is True

    def test_one_successful_real_call_is_finished_work(self) -> None:
        """A one-call task ("send the email") is done after its one call. A raw
        count floor here told the model the send may not have happened — and
        "do it now" can goad a duplicate send."""
        state = make_state(
            messages=[_task(), *_worked(1), AIMessage(content="sent")],
            todos=[],
        )

        assert work_looks_unfinished(state) is False

    def test_discovery_alone_is_not_work(self) -> None:
        state = make_state(
            messages=[
                _task(),
                AIMessage(content=""),
                ToolMessage(content="[tools]", tool_call_id="c1", name="retrieve_tools"),
                AIMessage(content="here is the answer"),
            ],
            todos=[],
        )

        assert work_looks_unfinished(state) is True

    def test_an_errored_call_is_not_work(self) -> None:
        state = make_state(
            messages=[
                _task(),
                AIMessage(content=""),
                ToolMessage(content="boom", tool_call_id="c1", status="error"),
                AIMessage(content="done"),
            ],
            todos=[],
        )

        assert work_looks_unfinished(state) is True

    def test_no_tool_calls_at_all_is_unfinished(self) -> None:
        state = make_state(
            messages=[_task(), AIMessage(content="here is the answer")],
            todos=[],
        )

        assert work_looks_unfinished(state) is True

    def test_a_thread_with_no_work_at_all_is_unfinished(self) -> None:
        state = make_state(messages=[_task(), AIMessage(content="I think it is 42.")], todos=[])

        assert work_looks_unfinished(state) is True

    def test_a_new_delegation_does_not_inherit_the_previous_one_s_tool_calls(self) -> None:
        """The bug this module's scoping fixes: delegation two answered from thin
        air, but the thread-wide count still saw delegation one's tools and let it
        stop."""
        state = make_state(
            messages=[
                _task("first task"),
                *_worked(5),
                AIMessage(content="finished one"),
                _task("second task"),
                AIMessage(content="I think it is 42."),
            ],
            todos=[],
        )

        assert work_looks_unfinished(state) is True

    def test_missing_todos_channel_is_treated_as_no_todos(self) -> None:
        state = make_state(messages=[_task(), *_worked(2), AIMessage(content="done")])
        state.pop("todos", None)

        assert work_looks_unfinished(state) is False

    def test_non_dict_todo_entries_are_ignored(self) -> None:
        """The channel is not schema-enforced; a stray string must not crash the
        guard or read as an open item."""
        state = make_state(
            messages=[_task(), *_worked(2), AIMessage(content="done")],
            todos=["pending", None],
        )

        assert work_looks_unfinished(state) is False


def _asked_task() -> HumanMessage:
    """A workflow delegation whose brief asks for a playbook decision."""
    return HumanMessage(content=f"triage the inbox\n\n{PLAYBOOK_CHECK_TAG}\n...\n</playbook_check>")


def _finished() -> list[AnyMessage]:
    """The executor ending through finish_task, as the finish node records it."""
    return [
        AIMessage(content="", tool_calls=[{"name": FINISH_TASK_NAME, "args": {}, "id": "f_1"}]),
        ToolMessage(content="Task completed.", tool_call_id="f_1", name=FINISH_TASK_NAME),
    ]


def _decision(name: str, *, ok: bool = True) -> list[AnyMessage]:
    """One round-trip on a playbook decision tool, as the tool node records it."""
    body = {"success": True, "data": {}} if ok else {"success": False, "error": "refused"}
    return [
        AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": "pb_1"}]),
        ToolMessage(content=json.dumps(body), tool_call_id="pb_1", name=name),
    ]


class TestPlaybookDecisionPending:
    """Seen live: 2 of 6 heal runs ended in plain text without calling
    write_playbook, decline_playbook or disable_playbook. The brief says a run
    that was asked and called neither is a lapse; the graph must not let that
    plain-text stop stand."""

    def test_a_run_that_was_not_asked_owes_nothing(self) -> None:
        state = make_state(messages=[_task(), *_worked(2), AIMessage(content="done")])

        assert playbook_decision_pending(state) is False

    def test_an_asked_run_that_decided_nothing_is_pending(self) -> None:
        state = make_state(messages=[_asked_task(), *_worked(2), AIMessage(content="done")])

        assert playbook_decision_pending(state) is True

    @pytest.mark.parametrize("name", sorted(PLAYBOOK_DECISION_TOOL_NAMES))
    def test_each_decision_tool_settles_it(self, name: str) -> None:
        state = make_state(
            messages=[_asked_task(), *_worked(1), *_decision(name), AIMessage(content="done")]
        )

        assert playbook_decision_pending(state) is False

    def test_an_empty_delegation_owes_nothing(self) -> None:
        assert playbook_decision_pending(make_state(messages=[])) is False

    def test_a_mid_run_tool_result_is_not_a_stop(self) -> None:
        """An ordinary tool result as the last message means the run is still
        going; only a finish_task result (or plain text) is a stop."""
        state = make_state(
            messages=[
                _asked_task(),
                *_worked(1),
                AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c8"}]),
                ToolMessage(content="ok", tool_call_id="c8", name="x"),
            ]
        )

        assert playbook_decision_pending(state) is False

    def test_an_errored_decision_call_does_not_settle_it(self) -> None:
        """The tool node marks a crashed decision call status="error"; that
        round-trip left the run exactly where it was."""
        state = make_state(
            messages=[
                _asked_task(),
                *_worked(1),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "decline_playbook", "args": {}, "id": "pb9"}],
                ),
                ToolMessage(
                    content=json.dumps({"success": True, "data": {}}),
                    tool_call_id="pb9",
                    name="decline_playbook",
                    status="error",
                ),
                AIMessage(content="done"),
            ]
        )

        assert playbook_decision_pending(state) is True

    def test_a_finish_task_stop_without_a_decision_is_pending(self) -> None:
        """Seen live: a briefed run ended through finish_task, not plain text,
        and the gate let it go. finish_task is a stop like any other."""
        state = make_state(messages=[_asked_task(), *_worked(2), *_finished()])

        assert playbook_decision_pending(state) is True

    def test_a_finish_task_stop_after_a_decision_owes_nothing(self) -> None:
        state = make_state(
            messages=[_asked_task(), *_worked(1), *_decision("decline_playbook"), *_finished()]
        )

        assert playbook_decision_pending(state) is False

    def test_a_tool_calling_turn_is_not_a_stop(self) -> None:
        """Mid-run, with a tool call outstanding, nothing is owed yet."""
        state = make_state(
            messages=[
                _asked_task(),
                *_worked(1),
                AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c9"}]),
            ]
        )

        assert playbook_decision_pending(state) is False

    def test_a_refused_write_is_not_a_decision(self) -> None:
        state = make_state(
            messages=[
                _asked_task(),
                *_worked(1),
                *_decision("write_playbook", ok=False),
                AIMessage(content="done"),
            ]
        )

        assert playbook_decision_pending(state) is True

    def test_reading_the_playbook_is_not_a_decision(self) -> None:
        state = make_state(
            messages=[_asked_task(), *_decision("read_playbook"), AIMessage(content="done")]
        )

        assert playbook_decision_pending(state) is True

    def test_a_previous_delegations_decision_does_not_carry_over(self) -> None:
        state = make_state(
            messages=[
                _asked_task(),
                *_decision("decline_playbook"),
                _asked_task(),
                *_worked(1),
                AIMessage(content="done"),
            ]
        )

        assert playbook_decision_pending(state) is True

    def test_a_tool_call_still_in_flight_is_not_a_plain_text_stop(self) -> None:
        """Only a plain-text stop is gated; the graph routes tool calls first."""
        state = make_state(messages=[_asked_task(), _decision("write_playbook")[0]])

        assert playbook_decision_pending(state) is False


class TestPlaybookNudgesSpent:
    def test_counts_only_the_current_delegations_decision_nudges(self) -> None:
        state = make_state(
            messages=[
                _asked_task(),
                HumanMessage(content=PLAYBOOK_DECISION_NUDGE_MESSAGE),
                _asked_task(),
                AIMessage(content="done"),
                HumanMessage(content=PLAYBOOK_DECISION_NUDGE_MESSAGE),
            ]
        )

        assert playbook_nudges_spent(state) == 1

    def test_the_decision_nudge_is_not_a_delegation_boundary(self) -> None:
        state = make_state(
            messages=[
                _asked_task(),
                *_worked(1),
                AIMessage(content="done"),
                HumanMessage(content=PLAYBOOK_DECISION_NUDGE_MESSAGE),
                AIMessage(content="still done"),
            ]
        )

        assert playbook_decision_pending(state) is True
        assert completion_nudges_spent(state) == 0

    def test_the_tag_quoted_inside_a_users_own_request_is_not_a_brief(self) -> None:
        state = make_state(
            messages=[
                HumanMessage(content=f"what does {PLAYBOOK_CHECK_TAG} mean in the code?"),
                *_worked(1),
                AIMessage(content="It marks a briefed run."),
            ]
        )

        assert playbook_decision_pending(state) is False
