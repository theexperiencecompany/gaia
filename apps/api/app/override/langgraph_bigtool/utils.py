"""
Utility functions for LangGraph bigtool agent.

Contains helper functions for tool selection formatting and type definitions.
"""

from typing import TypedDict

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool


class RetrieveToolsResult(TypedDict):
    """Result from retrieve_tools function.

    Attributes:
        tools_to_bind: List of tool IDs to bind to the model
        response: List of tool IDs to show in the response message
    """

    tools_to_bind: list[str]
    response: list[str]


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
                    tool_names.append(
                        getattr(tool_registry[result], "__name__", result)
                    )
            else:
                # Handle tools not in registry (e.g., subagent: prefixed)
                tool_names.append(result)

        tool_messages.append(
            ToolMessage(f"Available tools: {tool_names}", tool_call_id=tool_call_id)
        )
        tool_ids.extend(batch)

    return tool_messages, tool_ids
