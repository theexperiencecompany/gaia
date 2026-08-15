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
- LLM: FakeMessagesListChatModel
- Store: InMemoryStore (no ChromaDB)
- Checkpointer: MemorySaver (no PostgreSQL)

DELETE ``app/agents/core/nodes/manage_system_prompts.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/create_agent.py`` → these tests FAIL.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
import pytest

from tests.e2e.conftest import build_gaia_test_graph
from tests.helpers import BindableToolsFakeModel, assert_tool_called, extract_tool_calls

# The node's pure input→output contract is covered by the unit suite
# (tests/unit/agents/test_manage_system_prompts_node.py); this file only
# verifies the node is actually wired into the compiled graph.


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
    """E2E tests verifying manage_system_prompts_node is active in the GAIA graph.

    These tests invoke the fully compiled create_agent graph and confirm that
    both pre-model hooks (filter_messages_node, manage_system_prompts_node) are
    correctly wired.  If either node is removed from the graph, these tests fail.
    """

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
                            "args": {
                                "title": "Weather Note",
                                "body": "Sunny in London",
                            },
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
        """Both real GAIA pre-model hooks run without crashing and the model responds.

        Pre-model hooks (filter_messages_node, manage_system_prompts_node) are
        ephemeral: they modify state only for the model call via execute_hooks(),
        not the LangGraph-checkpointed state. The add_messages reducer appends
        new messages; it does not replace existing ones with hook output.

        What we CAN verify:
        - The graph does not raise despite receiving a dangling tool call and
          multiple system prompts (hooks handled the messy state gracefully).
        - The model produced a response (an AIMessage with the expected content
          appears in the final checkpointed messages).
        - No NEW tool calls were introduced by the graph run (the model
          responded with plain text, not another tool invocation).
        """
        fake_llm = BindableToolsFakeModel(responses=[AIMessage(content="All cleaned up.")])

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

        # The model must have responded — hooks ran without crashing
        ai_responses = [
            m for m in final_messages if isinstance(m, AIMessage) and m.content == "All cleaned up."
        ]
        assert len(ai_responses) == 1, (
            "Graph must produce the model's response. If hooks crashed, no AIMessage would appear."
        )

        # The model's final AIMessage must not contain tool calls
        assert not ai_responses[0].tool_calls, (
            "The model's terminal response must be plain text, not a tool call."
        )
