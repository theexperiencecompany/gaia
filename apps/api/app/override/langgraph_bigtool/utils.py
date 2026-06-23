"""
Utility functions for LangGraph bigtool agent.

Contains helper functions for tool selection formatting and type definitions.
"""

from collections.abc import Sequence
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.channels.delta import DeltaChannel
from langgraph.graph.message import _messages_delta_reducer
from langgraph_bigtool.graph import State as _BigtoolState

from app.constants.llm import MESSAGES_SNAPSHOT_FREQUENCY


def _replace_todos(_left: list, right: list) -> list:
    """Last-write-wins reducer for the todos channel."""
    return right


class State(_BigtoolState):
    """Extended state with todos channel for agent task management."""

    # Override MessagesState's plain add_messages channel with a DeltaChannel:
    # a full-snapshot channel re-serializes the entire message list into every
    # checkpoint, so a thread with N steps costs O(N²) storage (a single
    # runaway thread reached 17 GB). DeltaChannel persists only the per-step
    # delta and writes a full snapshot every MESSAGES_SNAPSHOT_FREQUENCY
    # updates. `_messages_delta_reducer` is LangGraph's batching-invariant
    # messages reducer (dedup by id + RemoveMessage tombstoning) built for
    # DeltaChannel's `(state, list[writes]) -> state` batch contract — plain
    # `add_messages` is a `(left, right)` reducer and is not compatible.
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(
            reducer=_messages_delta_reducer, snapshot_frequency=MESSAGES_SNAPSHOT_FREQUENCY
        ),
    ]
    todos: Annotated[list, _replace_todos]
    intent: str | None
    integration_usernames: dict[str, str]


class RetrieveToolsResult(TypedDict):
    """Result from retrieve_tools function.

    Attributes:
        tools_to_bind: List of tool IDs to bind to the model
        response: List of tool IDs to show in the response message
    """

    tools_to_bind: list[str]
    response: list[str]


def dedupe_str_list(items: Sequence[str]) -> list[str]:
    """Deduplicate strings while preserving first-seen order."""
    return list(dict.fromkeys(items))


def _tool_binding_key(tool: BaseTool) -> tuple[str, str | int]:
    """Build a stable key for tool binding de-duplication."""
    return ("name", tool.name)


def dedupe_tool_bindings(tools: Sequence[BaseTool]) -> list[BaseTool]:
    """Deduplicate tools for model binding while preserving order."""
    seen: set[tuple[str, str | int]] = set()
    deduped: list[BaseTool] = []
    for tool in tools:
        key = _tool_binding_key(tool)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tool)
    return deduped


def format_selected_tools(
    selected_tools: dict, tool_registry: dict[str, BaseTool]
) -> tuple[list[ToolMessage], list[str]]:
    """Format selected tools, gracefully handling tools not in registry.

    Handles tools like subagent: prefixed ones that may not be in the registry.

    Args:
        selected_tools: Dict mapping tool_call_id to list of tool IDs
        tool_registry: Dict mapping tool ID to tool instance

    Returns:
        Tuple of (tool_messages, tool_ids) where tool_messages show available tools
        and tool_ids are the IDs to bind
    """
    tool_messages = []
    tool_ids = []

    for tool_call_id, batch in selected_tools.items():
        tool_names = []
        for result in batch:
            # Handle tools that exist in registry
            if result in tool_registry:
                if isinstance(tool_registry[result], BaseTool):
                    tool_names.append(tool_registry[result].name)
                else:
                    tool_names.append(getattr(tool_registry[result], "__name__", result))
            else:
                # Handle tools not in registry (e.g., subagent: prefixed)
                tool_names.append(result)

        tool_messages.append(
            ToolMessage(f"Available tools: {tool_names}", tool_call_id=tool_call_id)
        )
        tool_ids.extend(batch)

    return tool_messages, tool_ids
