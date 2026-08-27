"""The executor tier as a running graph: tools that execute, state that changes,
and how a run ends.

Until now the executor was tested two ways, neither of which runs it:
``test_graph_builder.py`` mocks ``create_agent`` and asserts the kwargs it was
called with, and ``test_real_executor_agent.py`` compiles a graph but never
executes a tool. So the tier that owns every tool in the product had no test
that a tool call changes anything.

These drive the real compiled executor graph. Only the model is faked. The
assertions are about the graph's own contracts — which tools it will run without
retrieval, what a tool call does to the `todos` channel, what the pre-model hook
puts in front of the model, and how the run terminates.
"""

from __future__ import annotations

from itertools import takewhile
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from app.constants.llm import COMPLETION_NUDGE_MESSAGE
from tests.e2e._harness.graph_run import (
    AGENT_NODE,
    FINISH_NODE,
    NUDGE_NODE,
    REJECT_NODE,
    TOOLS_NODE,
    call,
    executor_graph,
    run_graph,
)

pytestmark = pytest.mark.e2e


def plan(*contents: str, id: str = "p1") -> dict[str, Any]:
    return call("plan_tasks", {"tasks": [{"content": c} for c in contents]}, id)


class TestToolsBoundFromTurnOne:
    """``initial_tool_ids`` is what the executor can do before it retrieves
    anything. A tool dropping out of that list is invisible until an agent
    stalls in production trying to use it."""

    @pytest.mark.parametrize(
        "tool",
        [
            "plan_tasks",
            "update_tasks",
            "handoff",
            "retrieve_tools",
            # spawn_subagent comes from the middleware stack rather than
            # initial_tool_ids, so it is the ONLY tool here that depends on
            # _get_bound_tool_names recognising middleware tools. Every other
            # entry is in both lists and passes either way.
            "spawn_subagent",
        ],
    )
    async def test_a_core_tool_needs_no_retrieval(self, tool: str):
        async with executor_graph([call(tool, {}, id="c1"), "ok"]) as graph:
            run = await run_graph(graph, "do the thing")

        assert REJECT_NODE not in run.nodes(), f"{tool} was treated as unbound"

    @pytest.mark.parametrize("tool", ["take_screenshot", "create_reminder_tool", "create_todo"])
    async def test_a_tool_outside_the_general_space_is_not_bound_by_default(self, tool: str):
        """Delegated and desktop tools are REGISTERED but live in their own
        tool_space, so the executor must retrieve them rather than call them
        outright — that is what routes them through the right owner.

        Registered on purpose: an unregistered name (a Composio tool whose
        category has not been provisioned) is rejected for simply not existing,
        which proves nothing about scoping. Adding one of these to
        ``initial_tool_ids`` turns this test red; adding an unregistered name
        does not, because the binder skips ids the registry does not know.
        """
        async with executor_graph([call(tool, {}, id="c1"), "ok"]) as graph:
            run = await run_graph(graph, "do the thing")

        assert REJECT_NODE in run.nodes()
        assert not run.ran(tool)


class TestMixedTurns:
    """A model turn is not all-or-nothing: it can emit one tool the graph has
    bound and one it never retrieved. Every other test here uses a turn that is
    entirely one or the other, which leaves the routing that has to do BOTH
    completely unexercised.
    """

    async def test_a_bound_tool_still_runs_when_a_sibling_call_is_unbound(self):
        """Routing must fan out. If the unbound branch short-circuited the rest,
        the plan would silently never run while the model was told only about
        the rejection — it would then retry the search and never notice."""
        async with executor_graph(
            [
                [
                    {
                        "name": "plan_tasks",
                        "args": {"tasks": [{"content": "step one"}]},
                        "id": "p1",
                    },
                    {"name": "web_search_tool", "args": {"query": "cats"}, "id": "s1"},
                ],
                "Planned, and I will retrieve the search tool.",
            ]
        ) as graph:
            run = await run_graph(graph, "plan and search")

        assert run.ran("plan_tasks"), "the bound tool was dropped because a sibling was unbound"
        assert [t["content"] for t in run.todos] == ["step one"]
        assert REJECT_NODE in run.nodes()
        assert not run.ran("web_search_tool")

    async def test_both_outcomes_are_reported_back_to_the_model(self):
        """The model needs the result AND the correction — with only one of
        them it either redoes work it already did or never learns what failed."""
        async with executor_graph(
            [
                [
                    {
                        "name": "plan_tasks",
                        "args": {"tasks": [{"content": "step one"}]},
                        "id": "p1",
                    },
                    {"name": "web_search_tool", "args": {"query": "cats"}, "id": "s1"},
                ],
                "Understood.",
            ]
        ) as graph:
            run = await run_graph(graph, "plan and search")

        assert run.result_for("plan_tasks")
        assert "web_search_tool" in " ".join(run.results_from(REJECT_NODE))


class TestTodoState:
    async def test_planning_writes_the_todos_channel(self):
        """``plan_tasks`` is a state-mutating tool: its whole effect is the
        `todos` channel, which drives the progress card and the pre-model hook."""
        async with executor_graph([plan("draft the email", "send it"), "Planned."]) as graph:
            run = await run_graph(graph, "email my landlord")

        assert [t["content"] for t in run.todos] == ["draft the email", "send it"]
        assert run.ran("plan_tasks")

    async def test_the_first_task_starts_in_progress_and_the_rest_wait(self):
        """The card renders this distinction, and the model reads it to know
        where it is. All-pending or all-in-progress are both wrong."""
        async with executor_graph([plan("one", "two", "three"), "Planned."]) as graph:
            run = await run_graph(graph, "do three things")

        assert [t["status"] for t in run.todos] == ["in_progress", "pending", "pending"]

    async def test_each_task_gets_its_own_id(self):
        """``update_tasks`` addresses tasks by id; duplicates would make a status
        update land on the wrong row."""
        async with executor_graph([plan("one", "two", "three"), "Planned."]) as graph:
            run = await run_graph(graph, "do three things")

        ids = [t["id"] for t in run.todos]
        assert len(set(ids)) == len(ids)
        assert all(ids)

    async def test_the_model_is_never_shown_a_raw_command_object(self):
        """A state-mutating tool returns a ``Command``; the graph must apply it,
        not stringify it. If it leaks, the model reads
        ``Command(update={'todos': [...]})`` where its plan summary should be —
        so the tool appears to have worked while the state change was lost."""
        async with executor_graph([plan("draft the email", "send it"), "Planned."]) as graph:
            run = await run_graph(graph, "email my landlord")

        result = run.result_for("plan_tasks") or ""
        assert not result.startswith("Command("), (
            "the tool's Command was rendered into the tool message instead of applied"
        )

    async def test_a_status_update_sees_the_plan_that_was_made(self):
        """``update_tasks`` reads the current plan out of the `todos` channel via
        InjectedState. If planning never wrote the channel, every update matches
        nothing and the checklist freezes mid-run while the agent narrates
        progress.

        The update adds a task by content rather than addressing one by id:
        ids are generated per run, so a scripted call cannot know one — but
        appending only produces three tasks if the two planned ones were
        actually injected.
        """
        async with executor_graph(
            [
                plan("first", "second"),
                call("update_tasks", {"updates": [{"content": "third"}]}, id="u1"),
                "Done.",
            ]
        ) as graph:
            run = await run_graph(graph, "do three things")

        assert [t["content"] for t in run.todos] == ["first", "second", "third"]
        assert "no changes" not in (run.result_for("update_tasks") or "")

    async def test_planning_reports_the_plan_back_to_the_model(self):
        async with executor_graph([plan("draft the email", "send it"), "Planned."]) as graph:
            run = await run_graph(graph, "email my landlord")

        result = run.result_for("plan_tasks")
        assert result is not None
        assert "2 tasks" in result
        assert "draft the email" in result

    async def test_planning_nothing_leaves_the_channel_empty(self):
        """An empty plan must not crash the tool or fabricate a task."""
        async with executor_graph([call("plan_tasks", {"tasks": []}, id="p1"), "ok"]) as graph:
            run = await run_graph(graph, "nothing to do")

        assert run.todos == []
        assert run.ran("plan_tasks")


class TestTodoContextHook:
    """The todo pre-model hook re-renders the plan into a SystemMessage before
    every model call, so the model always sees current state rather than the
    stale copy buried in its own tool history.

    The hook's rewrite is ephemeral — it never lands in the checkpoint — so the
    only place to observe it is the prompt the model actually received.
    """

    async def test_the_current_plan_is_put_in_front_of_the_model(self):
        async with executor_graph([plan("draft the email", "send it"), "Planned."]) as graph:
            run = await run_graph(graph, "email my landlord")

        context = run.system_slot("todo_context")
        assert context is not None, "the model was never shown the todo context"
        assert "draft the email" in context
        assert "send it" in context

    async def test_the_plan_appears_exactly_once(self):
        """The hook strips its previous copy before inserting a fresh one.
        Without that, every step would stack another checklist into the prompt
        and the model would act on a stale one."""
        async with executor_graph([plan("one", "two"), "Planned."]) as graph:
            run = await run_graph(graph, "do two things")

        slots = [
            m
            for m in run.last_prompt()
            if isinstance(m, SystemMessage) and m.additional_kwargs.get("todo_context")
        ]
        assert len(slots) == 1

    async def test_a_run_with_no_plan_still_gets_the_todo_instructions(self):
        """The slot is always injected — the model has to know the tool exists
        before it has ever planned anything."""
        async with executor_graph(["Nothing to plan."]) as graph:
            run = await run_graph(graph, "just answer me")

        assert run.system_slot("todo_context") is not None

    async def test_the_context_leads_the_prompt_so_gemini_keeps_it(self):
        """It must sit inside the leading run of SystemMessages: Gemini promotes
        only that contiguous block into system_instruction and silently drops any
        SystemMessage appearing after a non-system message."""
        async with executor_graph([plan("one", "two"), "Planned."]) as graph:
            run = await run_graph(graph, "do two things")

        prompt = run.last_prompt()
        leading = list(takewhile(lambda m: isinstance(m, SystemMessage), prompt))
        assert any(m.additional_kwargs.get("todo_context") for m in leading)


class TestTermination:
    async def test_finish_task_ends_the_run_with_its_own_result(self):
        """``finish_task`` is how a delegated run hands its answer back: the
        tool's ``result`` becomes the message the parent reads, not the model's
        trailing prose."""
        async with executor_graph(
            [call("finish_task", {"result": "Booked for Tuesday."}, id="f1"), "unreachable"]
        ) as graph:
            run = await run_graph(graph, "book me a table")

        assert run.results_from(FINISH_NODE) == ["Booked for Tuesday."]
        assert "unreachable" not in run.final_text()

    async def test_finish_task_wins_over_other_calls_in_the_same_turn(self):
        """A model that emits finish_task alongside more work has decided it is
        done; running the other calls would act after the answer was given."""
        async with executor_graph(
            [
                [
                    {
                        "name": "plan_tasks",
                        "args": {"tasks": [{"content": "late"}]},
                        "id": "p1",
                    },
                    {"name": "finish_task", "args": {"result": "Done."}, "id": "f1"},
                ],
                "unreachable",
            ]
        ) as graph:
            run = await run_graph(graph, "wrap up")

        assert run.results_from(FINISH_NODE) == ["Done."]
        assert TOOLS_NODE not in run.nodes(), "work ran after the task was declared finished"
        assert run.todos == []

    async def test_a_plain_answer_ends_the_run(self):
        async with executor_graph(["Here is your answer."]) as graph:
            run = await run_graph(graph, "a question")

        assert run.final_text() == "Here is your answer."
        # Zero tool calls on a delegated task is the "one lookup then assert a
        # conclusion" shape the completion guard exists to catch, so the run
        # takes its one nudge and then ends in plain text.
        assert run.nodes() == [AGENT_NODE, NUDGE_NODE, AGENT_NODE]

    async def test_finish_task_without_a_result_still_terminates(self):
        """Models omit optional args. A missing ``result`` must yield a usable
        completion message, not an empty one the parent reports as the answer."""
        async with executor_graph([call("finish_task", {}, id="f1")]) as graph:
            run = await run_graph(graph, "wrap up")

        assert run.results_from(FINISH_NODE) == ["Task completed."]


class TestRecursionWrapup:
    async def test_the_model_is_warned_before_it_runs_out_of_steps(self):
        """A long run that hits the hard limit dies with a GraphRecursionError
        and no partial answer. The wrap-up notice is the one chance the model
        gets to summarise what it found — injected per call, never persisted, so
        the only place it is observable is the prompt itself."""
        async with executor_graph(
            [call("plan_tasks", {"tasks": []}, id=f"c{i}") for i in range(30)]
        ) as graph:
            run = await run_graph(graph, "a long job", recursion_limit=10)

        shown = " ".join(str(m.content) for m in run.last_prompt())

        assert "almost out of steps" in shown, f"the model was never warned: {shown[-200:]!r}"
        assert "summarize what you" in shown, "warned without being told what to do about it"

    async def test_a_short_run_is_not_warned(self):
        """Control: warning on every turn would waste tokens and push the model
        to wrap up work it has plenty of budget for."""
        async with executor_graph(["done"]) as graph:
            run = await run_graph(graph, "a quick job", recursion_limit=50)

        shown = " ".join(str(m.content) for m in run.last_prompt())

        assert "almost out of steps" not in shown.lower()


class TestTheCompletionGuardIsPerDelegation:
    """The executor keeps ONE thread per conversation (``executor_{thread_id}``,
    ``subagent_runner.prepare_executor_execution``), so every delegation after
    the first replays a thread that already holds the previous one's messages.
    A guard that measures the whole thread instead of the current delegation
    spends itself on delegation one and is never armed again — which is the
    opposite of what a "did you actually finish?" check is for.
    """

    async def test_it_fires_again_on_the_next_delegation_of_the_same_thread(self):
        """Two zero-tool delegations on one thread. Both must be nudged."""
        async with executor_graph(["An answer."]) as graph:
            first = await run_graph(graph, "first task", thread_id="one-thread")
            second = await run_graph(graph, "second task", thread_id="one-thread")

        assert first.nodes() == [AGENT_NODE, NUDGE_NODE, AGENT_NODE]
        assert second.nodes() == [AGENT_NODE, NUDGE_NODE, AGENT_NODE], (
            "the guard spent its only nudge on the first delegation"
        )

    async def test_a_delegation_cannot_inherit_the_previous_one_s_tool_calls(self):
        """Delegation one does real work; delegation two does none and answers
        flat. The tool-call floor is about THIS task's depth, so the earlier
        task's ToolMessages must not satisfy it."""
        async with executor_graph(
            [
                call("retrieve_tools", {"exact_tool_names": ["web_search_tool"]}, id="r1"),
                call("web_search_tool", {"query": "cats"}, id="c1"),
                "Did the work.",
                "Flat answer.",
            ]
        ) as graph:
            first = await run_graph(graph, "do the research", thread_id="carry-over")
            second = await run_graph(graph, "quick follow-up", thread_id="carry-over")

        assert NUDGE_NODE not in first.nodes(), "two tool calls clear the floor on their own"
        assert NUDGE_NODE in second.nodes(), (
            "the second delegation cleared the floor on the first one's tool calls"
        )


class TestThreadContinuity:
    async def test_a_second_run_on_the_same_thread_sees_the_first(self):
        """The executor thread is derived from the conversation
        (``executor_{thread_id}``) so consecutive delegations share context.
        Losing that makes the executor re-ask for everything it was already told.
        """
        # Two entries per run: the answer, then the retry after the completion
        # nudge. The script cycles, so one entry each would let run two replay
        # run one's answer.
        async with executor_graph(
            ["First answer.", "First answer.", "Second answer.", "Second answer."]
        ) as graph:
            await run_graph(graph, "remember: the code is 1234", thread_id="shared")
            second = await run_graph(graph, "what was the code?", thread_id="shared")

        state = await graph.aget_state({"configurable": {"thread_id": "shared", "user_id": "u-1"}})
        # The completion nudge is delivered as a HumanMessage too, so it shows up
        # here; the user's OWN turns are what this test is about.
        human = [
            m
            for m in state.values["messages"]
            if isinstance(m, HumanMessage) and str(m.content) != COMPLETION_NUDGE_MESSAGE
        ]
        assert [str(m.content) for m in human] == [
            "remember: the code is 1234",
            "what was the code?",
        ]
        assert second.final_text() == "Second answer."

    async def test_separate_threads_do_not_share_history(self):
        """Two conversations must not leak into each other."""
        # Two entries per run — see the sibling test.
        async with executor_graph(
            ["First answer.", "First answer.", "Second answer.", "Second answer."]
        ) as graph:
            await run_graph(graph, "conversation one", thread_id="thread-a")
            await run_graph(graph, "conversation two", thread_id="thread-b")

        state_b = await graph.aget_state(
            {"configurable": {"thread_id": "thread-b", "user_id": "u-1"}}
        )
        human = [
            str(m.content)
            for m in state_b.values["messages"]
            if isinstance(m, HumanMessage) and str(m.content) != COMPLETION_NUDGE_MESSAGE
        ]
        assert human == ["conversation two"]
