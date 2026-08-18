"""The comms tier as a running graph.

Comms is the front door and is deliberately the *narrowest* agent in the
product: three things it can do (delegate to the executor, cancel that
delegation, remember and recall), no tool retrieval at all, and every reply
routed straight to the user. Its value comes from what it cannot do — a comms
agent that could reach the executor's tools would act on the user's accounts
without any of the delegation, approval, or streaming machinery in between.

``test_chat_stream.py`` covers what comms puts on the wire. This covers the
graph: which tools exist, what happens to a call for one that does not, the
end-of-turn hooks, and how a turn carries into the next.
"""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest

from app.constants.general import NEW_MESSAGE_BREAKER
from tests.e2e._harness.graph_run import (
    AGENT_NODE,
    REJECT_NODE,
    SELECT_NODE,
    TOOLS_NODE,
    call,
    comms_graph,
    memory_engine_of,
    run_graph,
)

pytestmark = pytest.mark.e2e


class TestCommsToolSurface:
    @pytest.mark.parametrize(
        "tool", ["call_executor", "cancel_executor", "add_memory", "search_memory"]
    )
    async def test_the_comms_tools_are_bound_from_the_start(self, tool: str):
        """Comms retrieves nothing, so anything it can do it must already have."""
        async with comms_graph([call(tool, {}, id="c1"), "ok"]) as graph:
            run = await run_graph(graph, "hello")

        assert REJECT_NODE not in run.nodes(), f"{tool} was not bound to comms"

    async def test_delegating_to_the_executor_actually_dispatches(self):
        """Being bound is not the same as working. The "bound" test above stays
        green whatever the tool returns, so this pins the one thing the user
        depends on: asking for real work hands it off and says so. Without it,
        comms answers "on it" and nothing is ever dispatched.

        Its own conversation, deliberately: ``call_executor`` takes a busy lock
        keyed on the thread (``executor:busy:{thread_id}``) with a 30-minute
        TTL, and a lock left by any earlier dispatch queues this one instead of
        starting it — which is a different, also-valid response and would make
        the assertion order-dependent.
        """
        async with comms_graph(
            [call("call_executor", {"task": "book a table"}, id="c1"), "On it."]
        ) as graph:
            run = await run_graph(graph, "book me a table", thread_id=f"dispatch-{uuid4()}")

        result = run.result_for("call_executor") or ""
        assert not result.startswith("Error"), result
        assert "task_id" in result, f"the handoff was never dispatched: {result!r}"

    @pytest.mark.parametrize("tool", ["plan_tasks", "handoff", "read", "bash", "deep_research"])
    async def test_an_executor_tool_is_not_reachable_from_comms(self, tool: str):
        """The tier boundary. If an executor tool were callable here it would run
        outside delegation — no executor thread, no todo plan, no approval gate,
        and nothing on the stream to show it happened."""
        async with comms_graph([call(tool, {}, id="c1"), "ok"]) as graph:
            run = await run_graph(graph, "do the thing")

        assert REJECT_NODE in run.nodes()
        assert TOOLS_NODE not in run.nodes()
        assert not run.ran(tool)

    async def test_comms_cannot_retrieve_its_way_to_more_tools(self):
        """``retrieve_tools`` is disabled on comms. If it were reachable, comms
        could bind the whole registry and the boundary above would be advisory."""
        async with comms_graph(
            [
                call(
                    "retrieve_tools",
                    {"query": "todo", "exact_tool_names": ["plan_tasks"]},
                    id="r1",
                ),
                "ok",
            ]
        ) as graph:
            run = await run_graph(graph, "get me a tool")

        assert SELECT_NODE not in run.nodes()
        assert run.bound_tools() == []
        assert REJECT_NODE in run.nodes()

    async def test_a_rejected_tool_still_lets_the_turn_finish(self):
        """The user must get an answer even when the model reached for something
        it does not have."""
        async with comms_graph([call("plan_tasks", {}, id="c1"), "Let me delegate that."]) as graph:
            run = await run_graph(graph, "do the thing")

        assert "Let me delegate that." in run.final_text()


class TestMemoryTools:
    async def test_recall_reaches_the_memory_engine_and_answers_the_model(self):
        """``ran()`` and "not None" are both satisfied by an error string — the
        memory tools resolve the user from ``config["metadata"]``, and a config
        missing it returns "Error: user_id not found in config" while still
        looking like a completed tool call. Assert the real result."""
        async with comms_graph(
            [call("search_memory", {"query": "coffee"}, id="m1"), "You like oat milk."]
        ) as graph:
            run = await run_graph(graph, "what do I drink?")
            engine = memory_engine_of(graph)

        result = run.result_for("search_memory") or ""
        assert not result.startswith("Error"), result
        assert "memories" in result
        engine.recall.assert_awaited()


class TestReplyShape:
    async def test_a_comms_reply_carries_the_message_break_marker(self):
        """The client splits a comms turn into bubbles on this marker. Only
        comms gets it — the executor's text is not user-facing — so it is the
        one signal that a reply came from the front door."""
        async with comms_graph(["Hi there."]) as graph:
            run = await run_graph(graph, "hello")

        assert run.final_text() == f"Hi there.{NEW_MESSAGE_BREAKER}"

    async def test_an_empty_model_reply_is_replaced_with_something_sayable(self):
        """A model that returns neither text nor a tool call would otherwise
        render as an empty bubble."""
        async with comms_graph([AIMessage(content="")]) as graph:
            run = await run_graph(graph, "hello")

        assert run.final_text().replace(NEW_MESSAGE_BREAKER, "")
        assert "Empty response" in run.final_text()


class TestEndOfTurnHooks:
    async def test_the_turn_runs_its_end_graph_hooks(self):
        """Follow-up suggestions and passive memory ingestion both hang off the
        end hook. If the graph stopped routing through it, chips would vanish and
        nothing said in conversation would ever be remembered.

        Asserted via ``visited``, not ``nodes()``: the end hooks are
        side-effecting and write no channels, so the node emits an empty update
        rather than echoing the message list back into the checkpoint."""
        async with comms_graph(["Hi there."]) as graph:
            run = await run_graph(graph, "hello")

        assert "end_graph_hooks" in run.visited

    async def test_the_hooks_run_after_the_model_not_before(self):
        async with comms_graph(["Hi there."]) as graph:
            run = await run_graph(graph, "hello")

        assert run.visited.index(AGENT_NODE) < run.visited.index("end_graph_hooks")


class TestSystemPromptSlots:
    """``manage_system_prompts_node`` keeps at most one system message per slot.

    It does not *inject* prompts — the chat service builds those upstream — so
    its whole job is collapsing accumulated copies. A checkpointed thread grows
    a fresh static prompt and a fresh dynamic-context block every turn; left
    alone they stack, the prompt grows without bound, and the model reads
    contradictory context from different turns.
    """

    async def test_stale_copies_of_a_slot_are_dropped_before_the_model_sees_them(self):
        stale = SystemMessage(content="You are GAIA. (turn 1)")
        fresh = SystemMessage(content="You are GAIA. (turn 3)")

        async with comms_graph(["Hi."]) as graph:
            run = await run_graph(
                graph,
                "hello",
                state={
                    "messages": [stale, fresh, HumanMessage(content="hello")],
                    "todos": [],
                },
            )

        systems = [m for m in run.last_prompt() if isinstance(m, SystemMessage)]
        assert len(systems) == 1, f"stale system prompts survived: {len(systems)}"
        assert "turn 3" in str(systems[0].content)

    async def test_the_surviving_prompt_leads_the_conversation(self):
        """Gemini promotes only the leading contiguous run of SystemMessages into
        system_instruction and silently drops any that follow a user turn."""
        async with comms_graph(["Hi."]) as graph:
            run = await run_graph(
                graph,
                "hello",
                state={
                    "messages": [
                        HumanMessage(content="hello"),
                        SystemMessage(content="You are GAIA."),
                    ],
                    "todos": [],
                },
            )

        prompt = run.last_prompt()
        assert isinstance(prompt[0], SystemMessage)

    async def test_only_the_latest_clock_reaches_the_model(self):
        """Time rides a HumanMessage so the system prefix stays byte-stable.
        Two clocks in one prompt is the model reading contradictory times."""
        from app.helpers.message_helpers import build_current_time_message

        old_clock = build_current_time_message(user_timezone="UTC")
        new_clock = build_current_time_message(user_timezone="UTC")

        async with comms_graph(["Hi."]) as graph:
            run = await run_graph(
                graph,
                "hello",
                state={
                    "messages": [old_clock, new_clock, HumanMessage(content="hello")],
                    "todos": [],
                },
            )

        clocks = [m for m in run.last_prompt() if "Current UTC Time" in str(m.content)]
        assert len(clocks) == 1


class TestAcrossTurns:
    async def test_history_accumulates_on_one_thread(self):
        async with comms_graph(["First answer.", "Second answer."]) as graph:
            await run_graph(graph, "first question", thread_id="shared")
            await run_graph(graph, "second question", thread_id="shared")
            state = await graph.aget_state(
                {"configurable": {"thread_id": "shared", "user_id": "u-1"}}
            )

        asked = [str(m.content) for m in state.values["messages"] if isinstance(m, HumanMessage)]
        assert asked == ["first question", "second question"]

    async def test_a_second_turn_shows_the_model_the_first(self):
        """Comms is the only tier that sees the user's own words, so losing the
        prior turn means it re-asks for what it was already told."""
        async with comms_graph(["Noted.", "Second answer."]) as graph:
            await run_graph(graph, "my code is 1234", thread_id="shared")
            run = await run_graph(graph, "what was it?", thread_id="shared")

        shown = " ".join(str(m.content) for m in run.last_prompt())
        assert "my code is 1234" in shown

    async def test_separate_threads_stay_separate(self):
        async with comms_graph(["A.", "B."]) as graph:
            await run_graph(graph, "conversation one", thread_id="a")
            run = await run_graph(graph, "conversation two", thread_id="b")

        shown = " ".join(str(m.content) for m in run.last_prompt())
        assert "conversation one" not in shown
