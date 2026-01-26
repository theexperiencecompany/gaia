"""
Trim Messages Node for the conversational graph.

This module provides functionality to trim messages from the conversation
state based on token limits while preserving context and conversation flow.
"""

from typing import TypeVar

from app.agents.llm.token_counter import get_token_counter
from app.config.loggers import chat_logger as logger
from langchain_core.messages import trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState
from langgraph.store.base import BaseStore

T = TypeVar("T", bound=MessagesState)


def trim_messages_node(state: T, config: RunnableConfig, store: BaseStore) -> T:
    """
    Trim messages from the conversation state based on token limits.

    This function processes the message history and trims older messages to stay
    within token limits while preserving the most recent and relevant conversation
    context. System messages are excluded from trimming to maintain context.

    TECHNICAL IMPLEMENTATION:
    ========================
    - Extracts model configuration from the runnable config
    - Uses langchain's trim_messages with "last" strategy to keep recent messages
    - Excludes system messages from trimming (include_system=False)
    - Uses token counter specific to the provider and model
    - Allows partial message trimming when needed

    Args:
        state: The current state of the conversation containing a "messages" key
               with a list of message objects
        config: RunnableConfig containing model configurations and settings
        store: BaseStore for any persistent storage needs

    Returns:
        Dict containing trimmed "messages" list that fits within token limits,
        or empty dict if insufficient messages or on error
    """
    try:
        messages = state.get("messages", [])

        # Skip if insufficient messages to process
        messages_list = list(messages) if hasattr(messages, "__iter__") else []
        if not messages_list or len(messages_list) < 2:
            return state

        # Extract model configuration from runnable config
        model_configurations = config.get("configurable", {})
        provider = model_configurations.get("provider", None)
        max_tokens = model_configurations.get("max_tokens", None)

        # Skip trimming if max_tokens is not configured
        if max_tokens is None or not isinstance(max_tokens, int):
            return state

        # Trim messages using langchain's trim_messages utility
        trimmed_messages = trim_messages(
            list(messages_list),
            strategy="last",  # Keep the most recent messages
            include_system=False,  # Preserve system messages
            max_tokens=max_tokens,
            allow_partial=True,  # Allow partial message trimming
            token_counter=get_token_counter(provider),
        )

        return {**state, "messages": trimmed_messages}  # type: ignore[return-value]

    except Exception as e:
        logger.error(f"Error in trim messages node: {e}")
        return state
