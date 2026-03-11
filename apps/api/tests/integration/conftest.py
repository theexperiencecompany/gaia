"""Integration test fixtures shared across all integration test modules."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from tests.factories import make_config, make_user


class SimpleState(BaseModel):
    """Minimal graph state for integration tests."""

    messages: Annotated[list, add_messages] = Field(default_factory=list)
    route: str = ""


@pytest.fixture
def memory_saver() -> MemorySaver:
    """Provide a fresh in-memory checkpointer per test."""
    return MemorySaver()


@pytest.fixture
def thread_config() -> dict:
    """Provide a unique thread_id config per test."""
    return {"configurable": {"thread_id": str(uuid4())}}


@pytest.fixture
def compiled_graph(memory_saver: MemorySaver):
    """Build a simple two-node graph (echo node) compiled with MemorySaver.

    The graph accepts messages in state, echoes the last human message
    content prefixed with 'Echo: ', and terminates.
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
def mock_providers():
    """Mock the global lazy provider registry to avoid real service init."""
    with patch("app.core.lazy_loader.providers") as mock_registry:
        mock_registry.get = MagicMock(return_value=None)
        mock_registry.aget = AsyncMock(return_value=None)
        mock_registry.register = MagicMock()
        mock_registry.is_available = MagicMock(return_value=False)
        mock_registry.is_initialized = MagicMock(return_value=False)
        yield mock_registry


@pytest.fixture
def sample_user() -> dict:
    return make_user()


@pytest.fixture
def sample_config() -> dict:
    return make_config()
