"""
Manage System Prompts Node for the conversational graph.

This module provides functionality to keep only the latest non-memory system prompt
while preserving all memory system messages in their original order.
"""

from typing import cast

from app.config.loggers import chat_logger as logger
from app.override.langgraph_bigtool.utils import State
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore


def _is_memory_system_message(msg: AnyMessage) -> bool:
    """Return whether a system message is marked as memory context."""
    additional_is_memory = bool(msg.additional_kwargs.get("memory_message", False))
    model_extra = getattr(msg, "model_extra", None)
    model_extra_is_memory = bool(
        model_extra.get("memory_message", False)
        if isinstance(model_extra, dict)
        else False
    )
    return additional_is_memory or model_extra_is_memory


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

        # Find the latest non-memory system prompt
        latest_non_memory_system_prompt_idx = None

        for idx, msg in enumerate(messages):
            if msg.type == "system":
                is_memory = _is_memory_system_message(msg)
                # Track the latest non-memory system prompt index
                if not is_memory:
                    latest_non_memory_system_prompt_idx = idx

        # Filter messages: keep all except old non-memory system prompts
        filtered_messages = []
        for idx, msg in enumerate(messages):
            if msg.type == "system":
                is_memory = _is_memory_system_message(msg)
                # Keep memory messages always
                if is_memory:
                    filtered_messages.append(msg)
                # Keep only the latest non-memory system prompt
                elif idx == latest_non_memory_system_prompt_idx:
                    filtered_messages.append(msg)
                # Skip older non-memory system prompts
            else:
                # Keep all non-system messages
                filtered_messages.append(msg)

        return cast(State, {**state, "messages": filtered_messages})

    except Exception as e:
        logger.error(f"Error in manage system prompts node: {e}")
        return state
