"""
Filter Messages Node for the conversational graph.

This module provides functionality to remove unanswered tool calls from AI messages
while preserving all other message types in their original order.
"""

from typing import TypeVar

from app.config.loggers import chat_logger as logger
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState
from langgraph.store.base import BaseStore

T = TypeVar("T", bound=MessagesState)


def filter_messages_node(state: T, config: RunnableConfig, store: BaseStore) -> T:
    """
    Filters out unanswered tool calls from AI messages.

    This node scans the message history to identify tool calls that have
    corresponding ToolMessage responses. For AI messages with tool calls,
    only the tool calls that have responses are kept. This ensures incomplete
    tool interactions are cleaned up from the message history.

    Args:
        state: The current state containing messages.
        config: Configuration for the runnable.
        store: The store for any required data persistence.

    Returns:
        The updated state with unanswered tool calls removed from AI messages.
    """
    try:
        # First pass: collect all tool call IDs that have corresponding ToolMessage responses
        answered_tool_call_ids = set()

        for msg in state["messages"]:
            if isinstance(msg, ToolMessage):
                answered_tool_call_ids.add(msg.tool_call_id)

        # Second pass: filter messages
        filtered_messages: list[AnyMessage] = []

        for msg in state["messages"]:
            # For AI messages with tool calls, filter out unanswered tool calls
            if isinstance(msg, AIMessage) and msg.tool_calls:
                # Filter tool_calls to only include those with responses
                answered_tool_calls = [
                    tc
                    for tc in msg.tool_calls
                    if tc.get("id") in answered_tool_call_ids
                ]

                # Create a new AI message with filtered tool calls
                # We need to preserve the message even if all tool calls are filtered out
                # because it might contain important content/reasoning
                filtered_msg = msg.model_copy()
                filtered_msg.tool_calls = answered_tool_calls
                filtered_messages.append(filtered_msg)
            else:
                # Keep all other messages as-is (SystemMessage, HumanMessage, ToolMessage, etc.)
                filtered_messages.append(msg)

        return {**state, "messages": filtered_messages}  # type: ignore[return-value]

    except Exception as e:
        logger.error(f"Error in filter messages node: {e}")
        return state
