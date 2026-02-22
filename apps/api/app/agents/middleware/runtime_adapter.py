"""
Runtime Adapter - Bridges langgraph_bigtool State with LangChain Runtime.

LangChain's AgentMiddleware expects a Runtime object with specific attributes.
This module creates adapters that provide the expected interface while working
with our langgraph_bigtool-based agent state.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.override.langgraph_bigtool.utils import State
from langchain.agents.middleware.types import (
    AgentState,
    ModelRequest,
    ToolCallRequest,
)
from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import StreamWriter


def _noop_stream_writer(_: object) -> None:
    """Default stream writer used when graph stream writer is unavailable."""
    return None


def to_agent_state(state: State | dict[str, Any]) -> AgentState[Any]:
    """Convert graph state into LangChain AgentState-compatible shape."""
    agent_state: AgentState[Any] = AgentState(messages=list(state.get("messages", [])))
    jump_to = state.get("jump_to")
    if jump_to in {"tools", "model", "end"}:
        agent_state["jump_to"] = jump_to
    if "structured_response" in state:
        agent_state["structured_response"] = state["structured_response"]
    return agent_state


@dataclass(frozen=True)
class BigtoolRuntime(Runtime[Any]):
    """
    Runtime adapter for langgraph_bigtool integration.

    Provides the interface expected by LangChain AgentMiddleware.before_model
    and AgentMiddleware.after_model hooks.

    Attributes:
        context: Optional context object (can be used for custom data)
        store: The langgraph BaseStore instance
        stream_writer: Optional stream writer for output
        previous: Previous state (if any)
        config: The RunnableConfig from the graph invocation
    """

    config: RunnableConfig | None = None

    @classmethod
    def from_graph_context(
        cls,
        config: RunnableConfig,
        store: BaseStore | None = None,
        context: Any = None,
        stream_writer: StreamWriter = _noop_stream_writer,
        previous: Any = None,
    ) -> "BigtoolRuntime":
        """Create runtime from graph invocation context."""
        return cls(
            context=context,
            store=store,
            stream_writer=stream_writer,
            previous=previous,
            config=config,
        )


@dataclass
class BigtoolToolRuntime(ToolRuntime[None, dict[str, Any]]):
    """
    Tool-specific runtime adapter for wrap_tool_call middleware.

    Provides context needed during tool execution wrapping.

    Attributes:
        context: Optional context object
        store: The langgraph BaseStore instance
        config: The RunnableConfig from the graph invocation
        tool_name: Name of the tool being executed
    """

    tool_name: str | None = None

    @classmethod
    def from_graph_context(
        cls,
        config: RunnableConfig,
        store: BaseStore | None = None,
        tool_name: str | None = None,
        state: dict[str, Any] | None = None,
        context: None = None,
        stream_writer: StreamWriter = _noop_stream_writer,
        tool_call_id: str | None = None,
    ) -> "BigtoolToolRuntime":
        """Create tool runtime with defaults suitable for middleware wrappers."""
        return cls(
            state={} if state is None else state,
            context=context,
            config=config,
            stream_writer=stream_writer,
            tool_call_id=tool_call_id,
            store=store,
            tool_name=tool_name,
        )


def create_model_request(
    model: BaseChatModel,
    state: State,
    runtime: BigtoolRuntime,
    tools: Sequence[BaseTool | dict[str, Any]],
    system_message: SystemMessage | None = None,
) -> ModelRequest:
    """
    Create a ModelRequest from langgraph_bigtool context.

    This is passed to wrap_model_call middleware.

    Args:
        model: The LLM being used
        state: Current graph state
        runtime: The BigtoolRuntime adapter
        tools: List of tools bound to the model
        system_message: Optional system message (extracted from messages)

    Returns:
        ModelRequest compatible with LangChain middleware
    """
    messages = list(state.get("messages", []))

    # Extract system message if present
    extracted_system = None
    non_system_messages = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            if extracted_system is None:
                extracted_system = msg
        else:
            non_system_messages.append(msg)

    # Use provided system_message or extracted one
    final_system = system_message or extracted_system

    # ModelRequest.state follows LangChain's AgentState schema.
    agent_state = to_agent_state(state)
    tools_for_request: list[BaseTool | dict[str, Any]] = [tool for tool in tools]

    return ModelRequest(
        model=model,
        messages=non_system_messages if final_system else messages,
        system_message=final_system,
        tool_choice=None,
        tools=tools_for_request,
        response_format=None,
        state=agent_state,
        runtime=runtime,
        model_settings={},
    )


def create_tool_call_request(
    tool_call: dict[str, Any],
    tool: BaseTool | None,
    state: State,
    runtime: BigtoolToolRuntime,
) -> ToolCallRequest:
    """
    Create a ToolCallRequest from langgraph_bigtool context.

    This is passed to wrap_tool_call middleware.

    Args:
        tool_call: The tool call dict with id, name, args
        tool: The resolved BaseTool instance (if found)
        state: Current graph state
        runtime: The BigtoolToolRuntime adapter

    Returns:
        ToolCallRequest compatible with LangChain middleware
    """
    # Convert dict to ToolCall TypedDict
    tc: ToolCall = {
        "name": tool_call.get("name", ""),
        "args": tool_call.get("args", {}),
        "id": tool_call.get("id"),
    }

    return ToolCallRequest(
        tool_call=tc,
        tool=tool,
        state=state,
        runtime=runtime,
    )
