"""E2E test: tool-call routing and the provider transcript in a live GAIA graph.

This file does NOT cover email sending: the send_email tool below is a local stub standing in
for "any tool". Real send-email coverage lives in tests/e2e/test_send_email_flow.py, which drives
the Gmail path through the real HTTP route and app.services.mail.mail_service.

Real here: app.override.langgraph_bigtool.create_agent over the GAIA State schema, and the model
node's call through ainvoke_llm, which lays out each tool call and its results before the model
sees them. Doubled: the LLM (a fake that rejects a request the way OpenAI does), the store
(InMemoryStore, no ChromaDB), the checkpointer (MemorySaver, no PostgreSQL), and the routed tool
itself; the graph infrastructure is production code.
"""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langchain_core.tools import tool
import pytest

from app.agents.llm.transcript import UNFINISHED_TOOL_RESULT
from tests.e2e.conftest import build_gaia_test_graph
from tests.helpers import BindableToolsFakeModel, assert_tool_called


class _OpenAIStrictFakeModel(BindableToolsFakeModel):
    """Refuse, as OpenAI's chat API does, a tool call not answered in the messages right after it."""

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        for index, message in enumerate(messages):
            if not isinstance(message, AIMessage) or not message.tool_calls:
                continue
            answered = []
            for follower in messages[index + 1 :]:
                if not isinstance(follower, ToolMessage):
                    break
                answered.append(follower.tool_call_id)
            if answered != [call["id"] for call in message.tool_calls]:
                raise ValueError("tool_call_ids did not have response messages")
        return super()._generate(messages, *args, **kwargs)


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email via the GAIA mock email tool."""
    return f"Email delivered to {to} re: {subject}"


@pytest.mark.e2e
class TestToolRoutingFlow:
    """E2E tests verifying tool calls route, and reach the model in a provider-valid shape."""

    async def test_a_result_backfilled_after_later_turns_reaches_the_model_beside_its_call(
        self, thread_config, in_memory_store, memory_saver
    ):
        """The 2026-11-26 executor thread: its backfilled result sat after two later turns."""
        call = {"id": "call_e260", "name": "send_email", "args": {}, "type": "tool_call"}
        fake_llm = _OpenAIStrictFakeModel(responses=[AIMessage(content="Here is where we are.")])
        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={"send_email": send_email},
            checkpointer=memory_saver,
            store=in_memory_store,
        )
        await graph.aupdate_state(
            thread_config,
            {
                "messages": [
                    HumanMessage(content="email carol"),
                    AIMessage(content="", tool_calls=[call]),
                    HumanMessage(content="add a todo"),
                    AIMessage(content="todo added"),
                    ToolMessage(content="interrupted", tool_call_id="call_e260", status="error"),
                ]
            },
            as_node="tools",
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="and now?")]}, config=thread_config
        )

        assert result["messages"][-1].content == "Here is where we are."

    async def test_an_unanswered_call_reaches_the_model_answered_as_unfinished(
        self, thread_config, in_memory_store, memory_saver
    ):
        call = {"id": "call_open", "name": "send_email", "args": {}, "type": "tool_call"}
        fake_llm = _OpenAIStrictFakeModel(responses=[AIMessage(content="It did not finish.")])
        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={"send_email": send_email},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(content="email carol"),
                    AIMessage(content="", tool_calls=[call]),
                ]
            },
            config=thread_config,
        )

        assert result["messages"][-1].content == "It did not finish."
        assert not any(
            isinstance(m, ToolMessage) and m.content == UNFINISHED_TOOL_RESULT
            for m in result["messages"]
        ), "the answer is the request's, never written into the thread"

    async def test_graph_routes_a_tool_call_end_to_end(
        self, thread_config, in_memory_store, memory_saver
    ):
        """Build a real GAIA graph with create_agent and verify tool routing end-to-end."""
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
            {"messages": [HumanMessage(content="Send an email to carol about the project")]},
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
        """The compiled graph must use GAIA State (with 'todos' channel), not MessagesState."""
        fake_llm = BindableToolsFakeModel(responses=[AIMessage(content="No tool needed here.")])

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
