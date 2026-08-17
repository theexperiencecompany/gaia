"""Chat-stream scenarios driven through the real compiled comms graph.

Where ``test_tool_visibility.py`` pins the frame contract with a scripted event
sequence, this file runs the actual GAIA graph — ``build_comms_graph``, the real
pre-model hooks, the real ``ToolNode``, the real memory tools — and asserts on
the SSE transcript the client would receive. Only the model is faked, and only
because a real one is not deterministic.

That makes these the tests that catch wiring regressions: a tool that runs but
never streams a card, a result that never joins back to its call, a hook that
replays last turn's tool calls into this turn's stream.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
import pytest

from app.helpers.agent_helpers import build_agent_config, execute_graph_streaming
from tests.e2e._harness import Transcript
from tests.e2e._harness.graph_run import comms_graph

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _registry(real_tool_registry):
    """Tool categories and display labels come from the real global registry."""


async def stream_turn(graph: Any, prompt: str, thread_id: str, user_id: str) -> Transcript:
    """Run one user turn through the graph and parse what the client sees.

    The run config comes from the production ``build_agent_config`` rather than
    a hand-rolled dict: tools read the user from ``config["metadata"]`` while the
    graph reads it from ``config["configurable"]``, and only the real builder
    populates both.
    """
    config = await build_agent_config(
        conversation_id=thread_id,
        user={"user_id": user_id, "email": f"{user_id}@test.local", "name": "Test User"},
        agent_name="comms_agent",
    )
    state = {"messages": [HumanMessage(content=prompt)]}
    chunks = [chunk async for chunk in execute_graph_streaming(graph, state, config)]
    return Transcript.from_chunks(chunks)


def _call(name: str, args: dict[str, Any], id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": id}


# ---------------------------------------------------------------------------
# Scenario 1 — the comms agent answers on its own
# ---------------------------------------------------------------------------


class TestPlainReply:
    async def test_a_plain_answer_streams_text_and_nothing_else(self):
        """No tool ran, so no tool card may appear. A stray ``tool_data`` frame
        here is a card the user sees for work that never happened."""
        async with comms_graph(["The answer is 42."]) as graph:
            transcript = await stream_turn(graph, "What is the meaning?", "t1", "u1")

        assert transcript.final_text() == "The answer is 42."
        assert transcript.of_kind("tool_data") == []
        assert transcript.of_kind("tool_output") == []
        assert transcript.is_done

    async def test_the_persisted_text_matches_what_was_streamed(self):
        """The completion marker feeds MongoDB; a mismatch means the reload of
        a conversation shows different text than the live turn did."""
        async with comms_graph(["Streamed and stored."]) as graph:
            transcript = await stream_turn(graph, "hi", "t1", "u1")

        assert transcript.complete_message() == transcript.final_text()


# ---------------------------------------------------------------------------
# Scenario 2 — a tool runs, and the user watches it happen
# ---------------------------------------------------------------------------


class TestToolTurn:
    async def test_the_call_its_arguments_and_its_result_all_reach_the_client(self):
        """The whole point of streaming tool calls: the card shows up with the
        arguments the model chose, and fills in with the real tool's output."""
        async with comms_graph(
            [
                _call("add_memory", {"content": "Dhruv drinks oat milk"}, id="tc_mem"),
                "Noted.",
            ]
        ) as graph:
            transcript = await stream_turn(graph, "remember: I drink oat milk", "t1", "u1")

        assert transcript.tool_names() == ["add_memory"]
        assert transcript.args("add_memory") == {"content": "Dhruv drinks oat milk"}
        # The id comes from the memory engine the tool called — proof the text
        # travelled engine -> tool -> ToolMessage -> SSE, not from a stub.
        assert (
            transcript.result_for("add_memory")
            == "Memory stored under 'general' (ID: mem-test-001)"
        )
        assert transcript.final_text() == "Noted."

    async def test_the_tool_card_precedes_its_result_on_the_wire(self):
        """The card must render before the result exists — that is what makes
        the tool call visible while it is still running."""
        async with comms_graph([_call("add_memory", {"content": "x"}, id="tc_mem"), "ok"]) as graph:
            transcript = await stream_turn(graph, "remember x", "t1", "u1")

        kinds = transcript.kinds()
        assert kinds.index("tool_data") < kinds.index("tool_output")

    async def test_the_result_carries_the_call_id_the_card_was_emitted_with(self):
        """The frontend joins on this id alone. If the ids disagree the card
        renders forever without ever showing a result."""
        async with comms_graph(
            [_call("add_memory", {"content": "x"}, id="tc_join"), "ok"]
        ) as graph:
            transcript = await stream_turn(graph, "remember x", "t1", "u1")

        assert transcript.tool_call("add_memory").tool_call_id == "tc_join"
        assert [o.tool_call_id for o in transcript.outputs()] == ["tc_join"]

    async def test_the_executor_handoff_is_visible_as_its_own_card(self):
        """``call_executor`` is how every non-trivial request leaves the comms
        tier; if it does not stream, the UI goes silent while work happens."""
        async with comms_graph(
            [_call("call_executor", {"task": "book a flight"}, id="tc_exec"), "On it."]
        ) as graph:
            transcript = await stream_turn(graph, "book me a flight", "t1", "u1")

        call = transcript.tool_call("call_executor")
        assert call.category == "executor"
        assert call.args == {"task": "book a flight"}

    async def test_two_tools_in_one_turn_each_get_their_own_card_and_result(self):
        async with comms_graph(
            [
                _call("add_memory", {"content": "likes tea"}, id="tc_1"),
                _call("search_memory", {"query": "tea"}, id="tc_2"),
                "Both done.",
            ]
        ) as graph:
            transcript = await stream_turn(graph, "remember and then search", "t1", "u1")

        assert transcript.tool_names() == ["add_memory", "search_memory"]
        assert transcript.result_for("add_memory") is not None
        assert transcript.result_for("search_memory") is not None
        assert transcript.final_text() == "Both done."


# ---------------------------------------------------------------------------
# Multi-turn — the pre-model hooks replay history every turn
# ---------------------------------------------------------------------------


class TestAcrossTurns:
    async def test_last_turns_tool_card_does_not_replay_into_this_turn(self):
        """Turn 2's pre-model hooks re-emit turn 1's ``AIMessage``, tool calls
        and all. Without the node gate in ``execute_graph_streaming`` the user
        sees turn 1's card appear again under turn 2's reply."""
        thread = f"t-{uuid4()}"
        async with comms_graph(
            [
                _call("add_memory", {"content": "first turn fact"}, id="tc_turn1"),
                "Stored it.",
                "Just chatting now.",
            ]
        ) as graph:
            first = await stream_turn(graph, "remember something", thread, "u1")
            second = await stream_turn(graph, "how are you?", thread, "u1")

        assert first.tool_names() == ["add_memory"]
        assert second.tool_names() == []
        assert second.of_kind("tool_output") == []
        assert second.final_text() == "Just chatting now."

    async def test_each_turn_persists_only_its_own_text(self):
        """The completion marker must not accumulate across turns — the second
        turn's stored message would otherwise contain the first turn's reply."""
        thread = f"t-{uuid4()}"
        async with comms_graph(["First reply.", "Second reply."]) as graph:
            first = await stream_turn(graph, "one", thread, "u1")
            second = await stream_turn(graph, "two", thread, "u1")

        assert first.complete_message() == "First reply."
        assert second.complete_message() == "Second reply."
