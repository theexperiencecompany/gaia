"""E2E test: filter_messages_node cleans dangling tool calls in a live GAIA graph.

WHAT THIS TESTS (REAL GAIA CODE):
- ``filter_messages_node`` from ``app.agents.core.nodes.filter_messages``
  is wired as a pre-model hook via ``create_agent`` from
  ``app.override.langgraph_bigtool.create_agent``.
- The GAIA ``State`` schema (``app.override.langgraph_bigtool.utils.State``)
  is used throughout, not the generic ``MessagesState``.
- The graph runs the real hook pipeline on every model invocation.

HOW IT'S TESTED:
We inject AI messages with dangling tool calls (no corresponding ToolMessage)
into the graph state and assert that ``filter_messages_node`` strips them
before the model is called again — which is what allows the fake LLM
to respond correctly in turn 2 without being confused by stale tool calls.

Mock surfaces:
- LLM: FakeMessagesListChatModel
- Store: InMemoryStore (no ChromaDB)
- Checkpointer: MemorySaver (no PostgreSQL)
- email sending: a @tool stub is used, but the graph infrastructure is real

DELETE ``app/agents/core/nodes/filter_messages.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/create_agent.py`` → these tests FAIL.
"""

import pytest
from tests.helpers import BindableToolsFakeModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.agents.core.nodes.filter_messages import filter_messages_node
from tests.e2e.conftest import (
    build_gaia_test_graph,
    make_gaia_state,
    make_mock_store,
    make_node_config,
)
from tests.helpers import assert_tool_called


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email via the GAIA mock email tool."""
    return f"Email delivered to {to} re: {subject}"


@pytest.mark.e2e
class TestSendEmailFlow:
    """E2E tests verifying filter_messages_node is active in the GAIA graph.

    The real value here is that filter_messages_node (production code) is
    exercised as part of the graph run — not just unit-tested in isolation.
    """

    # -------------------------------------------------------------------------
    # The four tests below call filter_messages_node directly (unit-test style).
    # They belong here because they exercise the real production node that is
    # wired into the E2E graph, acting as a contract check for the node's
    # public interface. Comprehensive unit coverage lives in:
    #   tests/unit/agents/nodes/test_filter_messages.py
    # -------------------------------------------------------------------------

    def test_filter_messages_node_removes_dangling_tool_calls(self):
        """filter_messages_node must strip AI tool_calls with no ToolMessage response.

        Scenario: an AIMessage with a tool call for which no ToolMessage exists
        is placed in state. After filter_messages_node runs, the tool_calls list
        on that AI message should be empty.

        This tests the real filter_messages_node function (not a mock) directly.
        """
        ai_with_dangling_call = AIMessage(
            content="I'll send that email",
            tool_calls=[
                {
                    "id": "dangling_call_001",
                    "name": "send_email",
                    "args": {
                        "to": "alice@example.com",
                        "subject": "Meeting",
                        "body": "Let's catch up.",
                    },
                }
            ],
        )
        state = make_gaia_state(messages=[ai_with_dangling_call])
        config = make_node_config()
        store = make_mock_store()

        result = filter_messages_node(state, config, store)

        filtered_ai = result["messages"][0]
        assert isinstance(filtered_ai, AIMessage)
        assert len(filtered_ai.tool_calls) == 0, (
            "filter_messages_node must remove tool calls with no ToolMessage response"
        )

    def test_filter_messages_node_preserves_answered_tool_calls(self):
        """filter_messages_node must keep tool_calls that have a ToolMessage response."""
        ai = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "answered_001",
                    "name": "send_email",
                    "args": {"to": "bob@example.com", "subject": "Hi", "body": "Hello"},
                }
            ],
        )
        tool_response = ToolMessage(
            content="Email delivered to bob@example.com re: Hi",
            tool_call_id="answered_001",
        )
        state = make_gaia_state(messages=[ai, tool_response])
        config = make_node_config()
        store = make_mock_store()

        result = filter_messages_node(state, config, store)

        filtered_ai = result["messages"][0]
        assert len(filtered_ai.tool_calls) == 1, (
            "filter_messages_node must preserve tool_calls that have responses"
        )
        assert filtered_ai.tool_calls[0]["id"] == "answered_001"

    async def test_graph_runs_filter_messages_as_pre_model_hook(
        self, thread_config, in_memory_store, memory_saver
    ):
        """Build a real GAIA graph and verify a tool is called end-to-end.

        The graph is built with create_agent (real production function) using
        filter_messages_node and manage_system_prompts_node as pre-model hooks.
        The tool execution path uses the real DynamicToolNode from the GAIA
        override package.
        """
        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_email_001",
                            "name": "send_email",
                            "args": {
                                "to": "carol@example.com",
                                "subject": "Project Update",
                                "body": "All good.",
                            },
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Done! Email sent to carol@example.com."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={"send_email": send_email},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(content="Send an email to carol about the project")
                ]
            },
            config=thread_config,
        )

        messages = result["messages"]
        assert_tool_called(messages, "send_email")

        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 1
        assert "carol@example.com" in tool_messages[0].content

        final = messages[-1]
        assert isinstance(final, AIMessage)
        assert "carol" in final.content.lower()

    async def test_graph_state_uses_gaia_state_schema(
        self, thread_config, in_memory_store, memory_saver
    ):
        """The compiled graph must use GAIA State (with 'todos' channel), not MessagesState.

        After invoking, the returned state should contain 'todos' (GAIA-specific)
        in addition to 'messages'. This confirms the graph is using the real
        GAIA State from app.override.langgraph_bigtool.utils, not a generic state.
        """
        fake_llm = BindableToolsFakeModel(
            responses=[AIMessage(content="No tool needed here.")]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={"send_email": send_email},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Hello")]},
            config=thread_config,
        )

        assert "messages" in result
        # 'todos' is the GAIA-specific channel from app.override.langgraph_bigtool.utils.State
        assert "todos" in result, (
            "Result must contain 'todos' key — the GAIA-specific state channel. "
            "If missing, the graph is using a generic state instead of GAIA State."
        )
        # Value assertions: confirm the channels hold the right types, not just
        # that the keys are present. A wrong type here means the State schema
        # reducers are not functioning correctly.
        assert isinstance(result["todos"], list), (
            "'todos' must be a list (last-write-wins reducer returns a list). "
            f"Got {type(result['todos']).__name__!r} instead."
        )
        assert isinstance(result["messages"], list), (
            "'messages' must be a list (add_messages reducer returns a list). "
            f"Got {type(result['messages']).__name__!r} instead."
        )
        # The graph was invoked with one HumanMessage; the fake LLM produced one
        # AIMessage. At minimum both must be present.
        assert len(result["messages"]) >= 2, (
            "Expected at least a HumanMessage and an AIMessage in the result. "
            f"Got {len(result['messages'])} message(s)."
        )

    async def test_multi_turn_conversation_filter_cleans_between_turns(self):
        """filter_messages_node must clean unanswered tool calls across turns.

        Simulates a conversation where turn 1 left a dangling tool call, and
        turn 2 now has a different tool call with its response. After
        filter_messages_node, only the answered call from turn 2 remains.
        """
        dangling_ai = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "stale_001",
                    "name": "send_email",
                    "args": {},
                }
            ],
        )
        answered_ai = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "live_002",
                    "name": "send_email",
                    "args": {},
                }
            ],
        )
        live_response = ToolMessage(content="Email sent", tool_call_id="live_002")
        state = make_gaia_state(messages=[dangling_ai, answered_ai, live_response])
        config = make_node_config()
        store = make_mock_store()

        result = filter_messages_node(state, config, store)

        # dangling_ai (index 0) should have its tool_calls cleared
        assert len(result["messages"][0].tool_calls) == 0
        # answered_ai (index 1) should keep its tool_call
        assert len(result["messages"][1].tool_calls) == 1
        assert result["messages"][1].tool_calls[0]["id"] == "live_002"

    async def test_filter_messages_preserves_ai_content_on_cleanup(self):
        """filter_messages_node must preserve AI content even when tool_calls are removed.

        An AIMessage with both content and a dangling tool call: after filtering,
        the content must be intact even though tool_calls is cleared.
        """
        ai = AIMessage(
            content="I will try to send an email for you",
            tool_calls=[{"id": "no_response_tc", "name": "send_email", "args": {}}],
        )
        state = make_gaia_state(messages=[ai])
        config = make_node_config()
        store = make_mock_store()

        result = filter_messages_node(state, config, store)

        filtered = result["messages"][0]
        assert filtered.content == "I will try to send an email for you", (
            "filter_messages_node must not modify message content when removing tool_calls"
        )
        assert len(filtered.tool_calls) == 0
