"""
Manage System Prompts Node for the conversational graph.

This module provides functionality to keep only the latest non-memory system prompt
while preserving all memory system messages in their original order.
"""

from app.config.loggers import chat_logger as logger
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from langgraph_bigtool.graph import State


def manage_system_prompts_node(
    state: State, config: RunnableConfig, store: BaseStore
) -> State:
    """
    Keep only the latest non-memory system prompt while preserving all memory messages.

    This node runs as a pre-model hook to ensure system prompts are managed properly
    even when users cancel generation (end_graph_hooks won't run in that case).

    Logic:
    - Keep ALL system messages with memory_message=True (these are important memories)
    - Keep ONLY the LATEST non-memory system prompt (the current agent prompt)
    - Remove all older non-memory system prompts

    Args:
        state: The current state containing messages.
        config: Configuration for the runnable.
        store: The store for any required data persistence.

    Returns:
        The updated state with only the latest non-memory system prompt.
    """
    try:
        messages = state.get("messages", [])

        # Skip if insufficient messages to process
        if not messages:
            return state

        # Single reverse scan to find the latest non-memory system prompt
        latest_non_memory_system_prompt_idx = None
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if msg.type == "system":
                is_memory = msg.additional_kwargs.get(
                    "memory_message", False
                ) or msg.model_extra.get("memory_message", False)
                if not is_memory:
                    latest_non_memory_system_prompt_idx = idx
                    break

        # Single forward pass to filter
        filtered_messages = []
        for idx, msg in enumerate(messages):
            if msg.type != "system":
                filtered_messages.append(msg)
                continue
            is_memory = msg.additional_kwargs.get(
                "memory_message", False
            ) or msg.model_extra.get("memory_message", False)
            if is_memory or idx == latest_non_memory_system_prompt_idx:
                filtered_messages.append(msg)

        return {**state, "messages": filtered_messages}

    except Exception as e:
        logger.error(f"Error in manage system prompts node: {e}")
        return state
