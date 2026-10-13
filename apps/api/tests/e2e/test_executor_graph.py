"""Drive the real compiled executor graph, with only the model faked.

Until now the executor was tested two ways, neither of which runs it: test_graph_builder.py mocks
create_agent and asserts the kwargs it was called with, and test_real_executor_agent.py compiles a
graph but never executes a tool. So the tier that owns every tool in the product had no test that
a tool call changes anything.

The assertions here are about the graph's own contracts: which tools it will run without
retrieval, what a tool call does to the todos channel, what the pre-model hook puts in front of
the model, and how the run terminates.
"""

from __future__ import annotations

from itertools import takewhile
import logging
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.errors import GraphRecursionError
import pytest

from app.agents.core.background import executor_runner
from app.agents.core.background.executor_runner import _ExecutorResult
from app.agents.core.background.session import ExecutorRun, RunKind
from app.agents.core.subagents.subagent_runner import SubagentExecutionContext
from app.agents.tools import manual_tool
from app.constants.executor import EXECUTOR_STEP_LIMIT_MESSAGE
from app.constants.general import EXECUTOR_INTEGRATION_ID
from app.constants.llm import (
    COMPLETION_NUDGE_MESSAGE,
    EXECUTOR_RECURSION_LIMIT,
    LOOP_GUARD_STOP_REPEAT,
)
from app.db.redis import redis_cache
from app.models.user_models import AuthenticatedUser
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
from tests.e2e.test_agent_chain import StreamingScriptedModel, streaming_model

pytestmark = pytest.mark.e2e


def plan(*contents: str, plan_id: str = "p1") -> dict[str, Any]:
    return call("plan_tasks", {"tasks": [{"content": c} for c in contents]}, plan_id)


class TestToolsBoundFromTurnOne:
    """initial_tool_ids is what the executor can do before it retrieves anything.

    A tool dropping out of that list is invisible until an agent stalls in
    production trying to use it.
    """

    @pytest.mark.parametrize(
        "tool",
        [
            "plan_tasks",
            "update_tasks",
            "handoff",
            "retrieve_tools",
            # spawn_subagent comes from the middleware stack, not
            # initial_tool_ids — it is the only tool here that depends on
            # _get_bound_tool_names recognising middleware tools.
            "spawn_subagent",
        ],
    )
    async def test_a_core_tool_needs_no_retrieval(self, tool: str):
        async with executor_graph([call(tool, {}, call_id="c1"), "ok"]) as graph:
            run = await run_graph(graph, "do the thing")

        assert REJECT_NODE not in run.nodes(), f"{tool} was treated as unbound"

    @pytest.mark.parametrize("tool", ["take_screenshot", "create_reminder_tool", "create_todo"])
    async def test_a_tool_outside_the_general_space_is_not_bound_by_default(self, tool: str):
        """Uses a REGISTERED tool outside its space — an unregistered name would pass for the wrong reason."""
        async with executor_graph([call(tool, {}, call_id="c1"), "ok"]) as graph:
            run = await run_graph(graph, "do the thing")

        assert REJECT_NODE in run.nodes()
        assert not run.ran(tool)


class TestMixedTurns:
    """A model turn is not all-or-nothing: it can emit one bound tool and one unretrieved one.

    Every other test here uses a turn that is entirely one or the other, which
    leaves the routing that has to do BOTH completely unexercised.
    """

    async def test_a_bound_tool_still_runs_when_a_sibling_call_is_unbound(self):
        """Guards against the unbound branch short-circuiting the rest of the turn."""
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
        """The model needs both the result and the rejection reported back, not just one."""
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
        """plan_tasks is a state-mutating tool: its whole effect is the todos channel."""
        async with executor_graph([plan("draft the email", "send it"), "Planned."]) as graph:
            run = await run_graph(graph, "email my landlord")

        assert [t["content"] for t in run.todos] == ["draft the email", "send it"]
        assert run.ran("plan_tasks")

    async def test_the_first_task_starts_in_progress_and_the_rest_wait(self):
        """All-pending or all-in-progress would both be wrong."""
        async with executor_graph([plan("one", "two", "three"), "Planned."]) as graph:
            run = await run_graph(graph, "do three things")

        assert [t["status"] for t in run.todos] == ["in_progress", "pending", "pending"]

    async def test_each_task_gets_its_own_id(self):
        """update_tasks addresses tasks by id; duplicates would land an update on the wrong row."""
        async with executor_graph([plan("one", "two", "three"), "Planned."]) as graph:
            run = await run_graph(graph, "do three things")

        ids = [t["id"] for t in run.todos]
        assert len(set(ids)) == len(ids)
        assert all(ids)

    async def test_the_model_is_never_shown_a_raw_command_object(self):
        """A leaked Command(update=...) repr would read as a plan summary while the state change was lost."""
        async with executor_graph([plan("draft the email", "send it"), "Planned."]) as graph:
            run = await run_graph(graph, "email my landlord")

        result = run.result_for("plan_tasks") or ""
        assert not result.startswith("Command("), (
            "the tool's Command was rendered into the tool message instead of applied"
        )

    async def test_a_status_update_sees_the_plan_that_was_made(self):
        """Adds a task by content, not id, since ids are generated per run and unknowable ahead of it."""
        async with executor_graph(
            [
                plan("first", "second"),
                call("update_tasks", {"updates": [{"content": "third"}]}, call_id="u1"),
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
        async with executor_graph([call("plan_tasks", {"tasks": []}, call_id="p1"), "ok"]) as graph:
            run = await run_graph(graph, "nothing to do")

        assert run.todos == []
        assert run.ran("plan_tasks")


class TestTodoContextHook:
    """The todo pre-model hook re-renders the plan into a SystemMessage before every model call.

    The rewrite is ephemeral — it never lands in the checkpoint — so the only
    place to observe it is the prompt the model actually received.
    """

    async def test_the_current_plan_is_put_in_front_of_the_model(self):
        async with executor_graph([plan("draft the email", "send it"), "Planned."]) as graph:
            run = await run_graph(graph, "email my landlord")

        context = run.system_slot("todo_context")
        assert context is not None, "the model was never shown the todo context"
        assert "draft the email" in context
        assert "send it" in context

    async def test_the_plan_appears_exactly_once(self):
        """The hook must strip its previous copy before inserting a fresh one."""
        async with executor_graph([plan("one", "two"), "Planned."]) as graph:
            run = await run_graph(graph, "do two things")

        slots = [
            m
            for m in run.last_prompt()
            if isinstance(m, SystemMessage) and m.additional_kwargs.get("todo_context")
        ]
        assert len(slots) == 1

    async def test_a_run_with_no_plan_still_gets_the_todo_instructions(self):
        """The slot is always injected, even before anything has been planned."""
        async with executor_graph(["Nothing to plan."]) as graph:
            run = await run_graph(graph, "just answer me")

        assert run.system_slot("todo_context") is not None

    async def test_the_context_leads_the_prompt_so_gemini_keeps_it(self):
        """Gemini only promotes the leading contiguous SystemMessage run into system_instruction."""
        async with executor_graph([plan("one", "two"), "Planned."]) as graph:
            run = await run_graph(graph, "do two things")

        prompt = run.last_prompt()
        leading = list(takewhile(lambda m: isinstance(m, SystemMessage), prompt))
        assert any(m.additional_kwargs.get("todo_context") for m in leading)


class TestTermination:
    async def test_finish_task_ends_the_run_with_its_own_result(self):
        """finish_task's result becomes the message the parent reads, not the model's trailing prose."""
        async with executor_graph(
            [call("finish_task", {"result": "Booked for Tuesday."}, call_id="f1"), "unreachable"]
        ) as graph:
            run = await run_graph(graph, "book me a table")

        assert run.results_from(FINISH_NODE) == ["Booked for Tuesday."]
        assert "unreachable" not in run.final_text()

    async def test_finish_task_wins_over_other_calls_in_the_same_turn(self):
        """Running the other calls would act after the answer was already given."""
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
        """A missing result must yield a usable completion message, not an empty one."""
        async with executor_graph([call("finish_task", {}, call_id="f1")]) as graph:
            run = await run_graph(graph, "wrap up")

        assert run.results_from(FINISH_NODE) == ["Task completed."]


class TestRecursionWrapup:
    async def test_the_model_is_warned_before_it_runs_out_of_steps(self):
        """The warning is the model's one chance to wrap up before the recursion limit kills the run."""
        async with executor_graph(
            [call("plan_tasks", {"tasks": []}, call_id=f"c{i}") for i in range(30)]
        ) as graph:
            run = await run_graph(graph, "a long job", recursion_limit=10)

        shown = " ".join(str(m.content) for m in run.last_prompt())

        assert "almost out of steps" in shown, f"the model was never warned: {shown[-200:]!r}"
        assert "Summarize what you" in shown, "warned without being told what to do about it"

    async def test_a_short_run_is_not_warned(self):
        """Control: warning on every turn would waste tokens on work with plenty of budget left."""
        async with executor_graph(["done"]) as graph:
            run = await run_graph(graph, "a quick job", recursion_limit=50)

        shown = " ".join(str(m.content) for m in run.last_prompt())

        assert "almost out of steps" not in shown.lower()

    async def test_a_model_slow_to_wrap_up_still_ends_with_its_report(self):
        """The live desk run: warned only ~3 turns from the limit, it died with no report delivered."""
        model = _SlowToWrapUp(responses=[AIMessage(content="unused")])
        async with executor_graph([], model=model) as graph:
            run = await run_graph(graph, "a long job", recursion_limit=EXECUTOR_RECURSION_LIMIT)
            snapshot = await graph.aget_state({"configurable": {"thread_id": "t-1"}})

        assert run.error is None, f"the run hit its step limit: {run.error}"
        assert run.final_text() == WRAPUP_REPORT
        assert all(_wrapup_notices(prompt) <= 1 for prompt in run.prompts), (
            "the notice piled up instead of riding once at the tail of each prompt"
        )
        assert not any(_is_wrapup_notice(m) for m in snapshot.values["messages"]), (
            "the notice was persisted, so the thread's next delegation would inherit it"
        )

    async def test_a_model_that_ignores_the_notice_still_stops_at_the_limit(self):
        """The notice is advice, not a stop: a run that never answers still ends in GraphRecursionError."""
        async with executor_graph(
            [call("read_manual", {"topic": _TOPICS[i % 2]}, call_id=f"c{i}") for i in range(40)]
        ) as graph:
            run = await run_graph(graph, "a long job", recursion_limit=20)

        assert isinstance(run.error, GraphRecursionError)
        assert any(_wrapup_notices(prompt) for prompt in run.prompts)

    async def test_the_model_node_writes_only_real_channels(self, caplog):
        """remaining_steps is a managed value: echoing it back was dropped with a warning every step."""
        caplog.set_level(logging.WARNING, logger="langgraph")
        async with executor_graph(
            [call("read_manual", {"topic": "goals"}, call_id="c1"), "Read it."]
        ) as graph:
            await run_graph(graph, "read the goals manual")

        unknown = [r.getMessage() for r in caplog.records if "unknown channel" in r.getMessage()]
        assert unknown == []


#: Two topics alternated so consecutive calls differ and the repeat guard stays out of it.
_TOPICS = ("goals", "memory")
WRAPUP_REPORT = "Report: checked everything, nothing left to do."
_WRAPUP_MARKER = "almost out of steps"
#: Tool turns a slow model still takes after it is first warned, before it answers.
_TURNS_TO_WRAP_UP = 3


def _is_wrapup_notice(message: BaseMessage) -> bool:
    return isinstance(message, HumanMessage) and _WRAPUP_MARKER in str(message.content)


def _wrapup_notices(prompt: list[BaseMessage]) -> int:
    return sum(1 for message in prompt if _is_wrapup_notice(message))


class _SlowToWrapUp(StreamingScriptedModel):
    """Works until warned, then takes _TURNS_TO_WRAP_UP more tool turns before its report.

    Streams like a real provider, so the executor runner reads its report as it would in production.
    """

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self._prompts.append(list(messages))
        warned_turns = sum(1 for prompt in self._prompts if _wrapup_notices(prompt))
        turn = len(self._prompts)
        if warned_turns > _TURNS_TO_WRAP_UP:
            message = AIMessage(content=WRAPUP_REPORT)
        else:
            topic = _TOPICS[turn % len(_TOPICS)]
            message = AIMessage(
                content="",
                tool_calls=[call("read_manual", {"topic": topic}, call_id=f"w{turn}")],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


async def _run_through_the_runner(model: StreamingScriptedModel) -> _ExecutorResult:
    """Run the real executor runner and stream driver over the real graph; only its preparation is doubled."""
    configurable = {"thread_id": "desk-run", "user_id": "u-1"}
    run = ExecutorRun(
        stream_id="desk-stream",
        conversation_id="desk-run",
        user=AuthenticatedUser(user_id="u-1", email="u@test.local"),
        kind=RunKind.LIVE,
        task_id="desk-task",
        user_message_id=None,
    )
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    async with executor_graph([], model=model) as graph:
        ctx = SubagentExecutionContext(
            subagent_graph=graph,
            agent_name="executor_agent",
            config=cast(
                Any,
                {
                    "configurable": configurable,
                    "metadata": {"user_id": "u-1"},
                    "recursion_limit": EXECUTOR_RECURSION_LIMIT,
                },
            ),
            configurable=cast(Any, configurable),
            integration_id=EXECUTOR_INTEGRATION_ID,
            initial_state=cast(Any, {"messages": [HumanMessage("run the desk")], "todos": []}),
            stream_id=run.stream_id,
        )
        with (
            patch.object(redis_cache, "redis", redis),
            patch.object(
                executor_runner, "prepare_executor_execution", AsyncMock(return_value=(ctx, None))
            ),
        ):
            return await executor_runner._execute_executor(
                "run the desk", cast(Any, configurable), run
            )


class TestAStepLimitedRunThroughTheRunner:
    """What a tracked todo's delivery receives: the runner's result, not the graph's."""

    async def test_a_run_that_wraps_up_hands_its_report_on_as_the_final_result(self):
        result = await _run_through_the_runner(
            _SlowToWrapUp(responses=[AIMessage(content="unused")])
        )

        assert (result.text, result.type) == (WRAPUP_REPORT, "final")

    async def test_a_run_that_never_answers_still_ends_in_the_step_limit_error(self):
        script = [
            call("read_manual", {"topic": _TOPICS[i % 2]}, call_id=f"c{i}") for i in range(60)
        ]

        result = await _run_through_the_runner(streaming_model(script))

        assert (result.text, result.type) == (EXECUTOR_STEP_LIMIT_MESSAGE, "error")


class TestARepeatedCallIsNotRerun:
    """The live desk run re-issued one identical edit 28 times; each ran, so the run spun to its limit."""

    async def test_the_call_past_the_repeat_limit_never_reaches_the_tool(self):
        repeats = LOOP_GUARD_STOP_REPEAT + 2
        script: list[Any] = [
            call("read_manual", {"topic": "goals"}, call_id=f"r{i}") for i in range(repeats)
        ]
        with patch.object(manual_tool, "get_manual", wraps=manual_tool.get_manual) as reads:
            async with executor_graph([*script, "Read it."]) as graph:
                # Refusal is background-only by contract; real runs carry that mode.
                run = await run_graph(
                    graph, "read the goals manual", recursion_limit=50, execution_mode="background"
                )

        assert reads.call_count == LOOP_GUARD_STOP_REPEAT - 1
        refused = run.results_from(TOOLS_NODE)[LOOP_GUARD_STOP_REPEAT - 1 :]
        assert len(refused) == repeats - (LOOP_GUARD_STOP_REPEAT - 1)
        assert all("Blocked without executing" in text for text in refused), refused
        assert run.final_text() == "Read it."

    async def test_the_same_call_once_per_delegation_is_never_refused(self):
        """The executor thread spans delegations: a streak counted per thread would refuse a fresh request."""
        delegations = LOOP_GUARD_STOP_REPEAT + 1
        script: list[Any] = []
        for i in range(delegations):
            script += [call("read_manual", {"topic": "goals"}, call_id=f"d{i}"), "Read it."]
        with patch.object(manual_tool, "get_manual", wraps=manual_tool.get_manual) as reads:
            async with executor_graph(script) as graph:
                for i in range(delegations):
                    await run_graph(graph, f"read the goals manual ({i})", thread_id="one-thread")

        assert reads.call_count == delegations


class TestTheCompletionGuardIsPerDelegation:
    """The executor keeps ONE thread per conversation (executor_{thread_id}).

    A guard that measures the whole thread instead of the current delegation
    spends itself on delegation one and is never armed again.
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
        """The tool-call floor is about THIS task; the earlier task's ToolMessages must not satisfy it."""
        async with executor_graph(
            [
                call("retrieve_tools", {"exact_tool_names": ["web_search_tool"]}, call_id="r1"),
                call("web_search_tool", {"query": "cats"}, call_id="c1"),
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
        """The executor thread is derived from the conversation so consecutive delegations share context."""
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
