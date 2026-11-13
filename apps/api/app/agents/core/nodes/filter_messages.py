"""
Filter Messages Node for the conversational graph.

This module provides functionality to remove unanswered tool calls from AI messages
while preserving all other message types in their original order.
"""

import time
from typing import TypeVar

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState
from langgraph.store.base import BaseStore

from app.constants.log_tags import LogTag
from app.models.agent_models import config_agent_name
from app.services.latency_metrics import observe_graph_node
from shared.py.wide_events import log

T = TypeVar("T", bound=MessagesState)


def filter_messages_node(state: T, config: RunnableConfig, store: BaseStore) -> T:  # noqa: ARG001 -- execute_hooks() passes state/config/store positionally
    """Strip unanswered tool calls from AI messages, timed as a graph node."""
    start = time.perf_counter()
    try:
        return _filter_messages(state)
    finally:
        observe_graph_node(
            time.perf_counter() - start, node="filter_messages", agent=config_agent_name(config)
        )


def _filter_messages(state: T) -> T:
    """Keep only the tool calls on AI messages that have a ToolMessage response."""
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
                    tc for tc in msg.tool_calls if tc.get("id") in answered_tool_call_ids
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

        return {**state, "messages": filtered_messages}  # type: ignore[return-value]  # generic T: dict literal can't satisfy an arbitrary MessagesState subclass

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error in filter messages node",
            error_type=type(e).__name__,
            error=str(e),
        )
        return state
