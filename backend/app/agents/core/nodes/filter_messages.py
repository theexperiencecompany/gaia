"""
Delete System Messages Node for the conversational graph.

This module provides functionality to remove system messages from the conversation
state while preserving all other message types in their original order.
"""
from typing import Callable, TypeVar

from app.config.loggers import chat_logger as logger
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState
from langgraph.store.base import BaseStore

T = TypeVar("T", bound=MessagesState)

def create_filter_messages_node(
    agent_name: str = "main_agent",
    allow_memory_system_messages: bool = False,
    remove_system_messages: bool = False,
) -> Callable[[T, RunnableConfig, BaseStore], T]:
    """Create a node that filters out system messages from the conversation state.
    Args:
        agent_name: Name of the agent whose system messages should be included.
        allow_empty_agent_name: If True, allows empty agent_name to skip filtering.
            If False, It filters out all the messages having empty names.
        remove_system_messages: If True, removes all system messages from the conversation.
            Except those marked as memory messages if allow_memory_system_messages is True.
            When this is True, make sure to add SystemMessage after this hook is executed if SystemMessage
            is required for the agent to function properly.
    Returns:
        A callable node that filters messages in the conversation state.
    """

    def filter_messages(state: T, config: RunnableConfig, store: BaseStore) -> T:
        """
        Filters out system messages from the conversation state.
        Args:
            state: The current state containing messages.
            config: Configuration for the runnable.
            store: The store for any required data persistence.
        Returns:
            The updated state with system messages removed.
        """
        try:
            allowed_tool_messages_ids = set()
            filtered_messages = []
            # Separate system messages for removal and keep others
            for msg in state["messages"]:
                msg_names = msg.name.split(",") if msg.name else []

                # Check if message is from the target agent
                is_from_target_agent = agent_name in msg_names

                # Note: ToolMessage doesn't have 'name' attribute like other messages
                # So we are allowing all tool messages that are invoked by AI messages

                # Check if message is an allowed tool message
                is_allowed_tool_message = (
                    isinstance(msg, ToolMessage)
                    and msg.tool_call_id in allowed_tool_messages_ids
                )

                # Check if memory system messages are allowed
                # Exclude agent system prompts if memory system messages are allowed
                is_allowed_memory_system_message = (
                    allow_memory_system_messages
                    and isinstance(msg, SystemMessage)
                    and msg.model_dump().get("memory_message", False)
                )

                is_system_message = remove_system_messages and isinstance(
                    msg, SystemMessage
                )

                # Keep message if it matches either condition
                if (
                    is_from_target_agent
                    or is_allowed_tool_message
                    or is_allowed_memory_system_message
                ) and not is_system_message:
                    filtered_messages.append(msg)

                    # If this is an AI message, track its tool call IDs for future tool messages
                    if isinstance(msg, AIMessage):
                        for tool_call in msg.tool_calls:
                            allowed_tool_messages_ids.add(tool_call.get("id"))

            return {**state, "messages": filtered_messages}  # type: ignore[return-value]

        except Exception as e:
            logger.error(f"Error in delete system messages node: {e}")
            return state

    return filter_messages
