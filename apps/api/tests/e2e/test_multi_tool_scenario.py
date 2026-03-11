"""E2E test: manage_system_prompts_node deduplicates system prompts in multi-turn graphs.

WHAT THIS TESTS (REAL GAIA CODE):
- ``manage_system_prompts_node`` from ``app.agents.core.nodes.manage_system_prompts``
  is wired as a real pre-model hook via ``create_agent`` from
  ``app.override.langgraph_bigtool.create_agent``.
- In a multi-turn graph, only the LATEST non-memory SystemMessage is kept;
  older non-memory system prompts are removed.
- Memory-marked SystemMessages (``additional_kwargs={"memory_message": True}``)
  are preserved across turns regardless of position.
- ``filter_messages_node`` (also a real GAIA node) runs before
  ``manage_system_prompts_node`` in the hook chain.

Mock surfaces:
- LLM: BindableToolsFakeModel (wraps FakeMessagesListChatModel with bind_tools support)
- Store: InMemoryStore (no ChromaDB)
- Checkpointer: MemorySaver (no PostgreSQL)

DELETE ``app/agents/core/nodes/manage_system_prompts.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/create_agent.py`` → these tests FAIL.
"""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from tests.e2e.conftest import (
    build_gaia_test_graph,
    make_gaia_state,
    make_mock_store,
    make_node_config,
)
from tests.helpers import BindableToolsFakeModel, assert_tool_called, extract_tool_calls


@tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Sunny in {city}, 22°C."


@tool
def create_note(title: str, body: str) -> str:
    """Create a note with a title and body."""
    return f"Note '{title}' saved."


@pytest.mark.e2e
class TestMultiToolScenario:
    """E2E tests verifying manage_system_prompts_node is active in the GAIA graph."""

    def test_manage_system_prompts_keeps_only_latest_non_memory_prompt(self):
        """manage_system_prompts_node must remove all but the latest non-memory SystemMessage.

        Given two non-memory SystemMessages, only the last one should remain.
        This is the core contract of manage_system_prompts_node.
        """
        old_prompt = SystemMessage(content="Old system prompt from turn 1")
        new_prompt = SystemMessage(content="New system prompt from turn 2")
        human = HumanMessage(content="What is the weather?")

        state = make_gaia_state(messages=[old_prompt, human, new_prompt])
        config = make_node_config()
        store = make_mock_store()

        result = manage_system_prompts_node(state, config, store)

        system_messages = [m for m in result["messages"] if isinstance(m, SystemMessage)]
        assert len(system_messages) == 1, (
            "manage_system_prompts_node must keep only the latest non-memory system prompt"
        )
        assert system_messages[0].content == "New system prompt from turn 2"

    def test_manage_system_prompts_preserves_memory_messages(self):
        """manage_system_prompts_node must preserve SystemMessages marked as memory.

        Memory system messages use additional_kwargs={'memory_message': True}.
        They must never be removed, even when there are multiple non-memory prompts.
        """
        memory_prompt = SystemMessage(
            content="User prefers concise answers.",
            additional_kwargs={"memory_message": True},
        )
        old_system = SystemMessage(content="Old system prompt")
        new_system = SystemMessage(content="New system prompt")
        human = HumanMessage(content="Tell me something")

        state = make_gaia_state(messages=[memory_prompt, old_system, human, new_system])
        config = make_node_config()
        store = make_mock_store()

        result = manage_system_prompts_node(state, config, store)

        system_messages = [m for m in result["messages"] if isinstance(m, SystemMessage)]
        assert len(system_messages) == 2, (
            "manage_system_prompts_node must keep memory messages AND the latest non-memory prompt"
        )
        memory_msgs = [m for m in system_messages if m.additional_kwargs.get("memory_message")]
        assert len(memory_msgs) == 1
        assert memory_msgs[0].content == "User prefers concise answers."
        non_memory_msgs = [m for m in system_messages if not m.additional_kwargs.get("memory_message")]
        assert non_memory_msgs[0].content == "New system prompt"

    def test_manage_system_prompts_no_system_messages_is_noop(self):
        """manage_system_prompts_node must be a no-op when no SystemMessages exist."""
        state = make_gaia_state(
            messages=[
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there!"),
            ]
        )
        config = make_node_config()
        store = make_mock_store()

        result = manage_system_prompts_node(state, config, store)

        assert len(result["messages"]) == 2
        assert result["messages"][0].content == "Hello"
        assert result["messages"][1].content == "Hi there!"

    def test_manage_system_prompts_single_prompt_is_preserved(self):
        """manage_system_prompts_node must keep the single non-memory SystemMessage."""
        state = make_gaia_state(
            messages=[
                SystemMessage(content="Only system prompt"),
                HumanMessage(content="Hello"),
            ]
        )
        config = make_node_config()
        store = make_mock_store()

        result = manage_system_prompts_node(state, config, store)

        system_msgs = [m for m in result["messages"] if isinstance(m, SystemMessage)]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "Only system prompt"

    async def test_graph_calls_two_tools_in_sequence(
        self, thread_config, in_memory_store, memory_saver
    ):
        """Build a real GAIA graph and verify sequential tool calls work end-to-end.

        The graph uses manage_system_prompts_node and filter_messages_node as
        real pre-model hooks. Two tools are called in sequence: get_weather then
        create_note. We verify both ToolMessages appear in the final state.
        """
        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_weather_001",
                            "name": "get_weather",
                            "args": {"city": "London"},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_note_001",
                            "name": "create_note",
                            "args": {"title": "Weather Note", "body": "Sunny in London"},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="I got the weather and saved your note."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={"get_weather": get_weather, "create_note": create_note},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Get London weather and save a note")]},
            config=thread_config,
        )

        messages = result["messages"]
        assert_tool_called(messages, "get_weather")
        assert_tool_called(messages, "create_note")

        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 2

    async def test_tool_call_order_is_preserved_in_messages(
        self, thread_config, in_memory_store, memory_saver
    ):
        """Tool calls in the message history must appear in the order they were executed."""
        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_w1",
                            "name": "get_weather",
                            "args": {"city": "Paris"},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_n1",
                            "name": "create_note",
                            "args": {"title": "Paris Weather", "body": "Cloudy"},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Done."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={"get_weather": get_weather, "create_note": create_note},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Weather then note")]},
            config=thread_config,
        )

        tool_calls = extract_tool_calls(result["messages"])
        names = [tc["name"] for tc in tool_calls]

        weather_idx = names.index("get_weather")
        note_idx = names.index("create_note")
        assert weather_idx < note_idx, (
            "get_weather must be called before create_note in the message history"
        )

    async def test_filter_and_manage_hooks_both_run_as_pre_model_hooks(
        self, thread_config, in_memory_store, memory_saver
    ):
        """Both real GAIA pre-model hooks run in sequence on each model invocation.

        We inject a stale system prompt AND a dangling tool call. After the
        graph processes a new message, the final state should show:
        1. Only the latest system prompt (manage_system_prompts_node did its job)
        2. No unanswered tool calls remain (filter_messages_node did its job)
        """
        fake_llm = BindableToolsFakeModel(
            responses=[AIMessage(content="All cleaned up.")]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={"get_weather": get_weather},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        # Seed the graph with a stale system prompt and a dangling tool call
        old_system = SystemMessage(content="Old system prompt - should be removed")
        dangling_ai = AIMessage(
            content="",
            tool_calls=[{"id": "stale_tc", "name": "get_weather", "args": {"city": "X"}}],
        )
        new_system = SystemMessage(content="Current system prompt - should be kept")

        result = await graph.ainvoke(
            {
                "messages": [
                    old_system,
                    dangling_ai,
                    new_system,
                    HumanMessage(content="Now proceed"),
                ]
            },
            config=thread_config,
        )

        final_messages = result["messages"]

        # Verify manage_system_prompts_node removed old_system
        system_msgs = [m for m in final_messages if isinstance(m, SystemMessage)]
        assert all(m.content != "Old system prompt - should be removed" for m in system_msgs), (
            "manage_system_prompts_node must remove old non-memory system prompts"
        )

        # Verify filter_messages_node cleared the dangling tool_call
        ai_msgs_with_calls = [
            m for m in final_messages
            if isinstance(m, AIMessage) and m.tool_calls
            and any(tc["id"] == "stale_tc" for tc in m.tool_calls)
        ]
        assert len(ai_msgs_with_calls) == 0, (
            "filter_messages_node must remove dangling (unanswered) tool calls"
        )
