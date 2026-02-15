"""
Runtime Adapter - Bridges langgraph_bigtool State with LangChain Runtime.

LangChain's AgentMiddleware expects a Runtime object with specific attributes.
This module creates adapters that provide the expected interface while working
with our langgraph_bigtool-based agent state.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from langchain.agents.middleware.types import (
    ModelRequest,
    ToolCallRequest,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.store.base import BaseStore
from langgraph_bigtool.graph import State


@dataclass
class BigtoolRuntime:
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

    context: Any = None
    store: Optional[BaseStore] = None
    stream_writer: Any = None
    previous: Any = None
    config: Optional[RunnableConfig] = None

    @classmethod
    def from_graph_context(
        cls,
        config: RunnableConfig,
        store: Optional[BaseStore] = None,
        context: Any = None,
    ) -> "BigtoolRuntime":
        """Create runtime from graph invocation context."""
        return cls(
            context=context,
            store=store,
            config=config,
        )


@dataclass
class BigtoolToolRuntime:
    """
    Tool-specific runtime adapter for wrap_tool_call middleware.

    Provides context needed during tool execution wrapping.

    Attributes:
        context: Optional context object
        store: The langgraph BaseStore instance
        config: The RunnableConfig from the graph invocation
        tool_name: Name of the tool being executed
    """

    context: Any = None
    store: Optional[BaseStore] = None
    config: Optional[RunnableConfig] = None
    tool_name: Optional[str] = None


@dataclass
class BigtoolAgentState:
    """
    AgentState adapter for langgraph_bigtool State.

    Wraps our State TypedDict to provide the interface expected by
    LangChain middleware's AgentState.
    """

    messages: list[AnyMessage] = field(default_factory=list)
    selected_tool_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_state(cls, state: State) -> "BigtoolAgentState":
        """Create from langgraph_bigtool State."""
        return cls(
            messages=list(state.get("messages", [])),
            selected_tool_ids=list(state.get("selected_tool_ids", [])),
        )

    def to_state_update(self) -> dict[str, Any]:
        """Convert back to State update dict."""
        return {
            "messages": self.messages,
            "selected_tool_ids": self.selected_tool_ids,
        }


def create_model_request(
    model: BaseChatModel,
    state: State,
    runtime: BigtoolRuntime,
    tools: list[BaseTool],
    system_message: Optional[SystemMessage] = None,
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

    # Create state wrapper — pass full state so middleware can access all channels
    agent_state = dict(state)  # type: ignore[arg-type]

    return ModelRequest(
        model=model,
        messages=non_system_messages if final_system else messages,
        system_message=final_system,
        tool_choice=None,
        tools=tools,
        response_format=None,
        state=agent_state,
        runtime=runtime,
        model_settings={},
    )


def create_tool_call_request(
    tool_call: dict[str, Any],
    tool: Optional[BaseTool],
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
