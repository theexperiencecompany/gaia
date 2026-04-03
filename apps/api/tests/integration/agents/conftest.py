"""Agent-specific integration test fixtures."""

from typing import Any
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from tests.helpers import create_fake_llm, create_fake_llm_with_tool_calls
from tests.integration.conftest import SimpleState


@pytest.fixture
def simple_tool():
    """A trivial tool for testing tool execution in graphs."""

    @tool
    def greet(name: str) -> str:
        """Greet a person by name."""
        return f"Hello, {name}!"

    return greet


@pytest.fixture
def tool_calling_llm(simple_tool) -> FakeMessagesListChatModel:
    """Fake LLM that first emits a tool call, then a final text response."""
    tool_call = {
        "name": "greet",
        "args": {"name": "World"},
        "id": "call_greet_001",
        "type": "tool_call",
    }
    return create_fake_llm_with_tool_calls([tool_call, "Greeting complete."])


@pytest.fixture
def agent_graph_with_tools(simple_tool, tool_calling_llm, memory_saver):
    """Build a model+tool graph: model node -> conditional -> tool node -> model node.

    Uses the react agent pattern: if the model returns tool calls,
    route to the tool node; otherwise route to END.
    """

    def should_continue(state: SimpleState) -> str:
        last = state.messages[-1] if state.messages else None
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return "end"

    def model_node(state: SimpleState) -> dict[str, Any]:
        response = tool_calling_llm.invoke(state.messages)
        return {"messages": [response]}

    tool_node = ToolNode([simple_tool])

    builder = StateGraph(SimpleState)
    builder.add_node("model", model_node)
    builder.add_node("tools", tool_node)
    builder.set_entry_point("model")
    builder.add_conditional_edges(
        "model",
        should_continue,
        {"tools": "tools", "end": END},
    )
    builder.add_edge("tools", "model")

    return builder.compile(checkpointer=memory_saver)


@pytest.fixture
def echo_graph(memory_saver):
    """Fake echo graph that replies with 'Echo: <last message content>'.

    Kept for backward compatibility with any tests that depend on this fixture.
    The graph simply echoes the last human message content back as an AI message.
    Uses real Postgres checkpointer when USE_REAL_SERVICES=1, otherwise MemorySaver.
    """

    def echo_node(state: SimpleState) -> dict[str, Any]:
        last_msg = state.messages[-1] if state.messages else None
        content = last_msg.content if last_msg else "empty"
        return {"messages": [AIMessage(content=f"Echo: {content}")]}

    builder = StateGraph(SimpleState)
    builder.add_node("echo", echo_node)
    builder.set_entry_point("echo")
    builder.add_edge("echo", END)

    return builder.compile(checkpointer=memory_saver)


@pytest.fixture
def real_agent_config() -> dict:
    """Minimal config dict compatible with production LangGraph agent invocations.

    Provides a unique thread_id per test so checkpointer state does not leak
    between test runs, and a user_id that matches the format used in production.
    """
    return {
        "configurable": {
            "thread_id": str(uuid4()),
            "user_id": str(uuid4()),
        }
    }


@pytest.fixture
def fake_llm() -> FakeMessagesListChatModel:
    """A FakeMessagesListChatModel pre-loaded with a single plain-text response.

    Use this fixture when a test needs a properly configured LLM stand-in that
    can be bound to tools and invoked via the standard LangChain interface
    without hitting any external API.

    Example::

        def test_something(fake_llm):
            result = fake_llm.invoke([HumanMessage(content="hello")])
            assert result.content == "Fake response"
    """
    return create_fake_llm(["Fake response"])
