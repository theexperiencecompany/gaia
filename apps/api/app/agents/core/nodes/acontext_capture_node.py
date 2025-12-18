"""Acontext Node for capturing subagent executions.

This module provides a node that captures all messages from a subagent execution
and sends them to Acontext for skill learning. It runs as an end_graph_hook.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config.acontext_spaces import get_subagent_session, get_subagent_space
from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.core.acontext_client import get_acontext_client
from app.override.langgraph_bigtool.create_agent import HookType
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from langgraph_bigtool.graph import State


def _convert_message_to_acontext(message: BaseMessage) -> Optional[Dict[str, Any]]:
    """Convert a LangChain message to Acontext format.

    Args:
        message: LangChain message

    Returns:
        Acontext-formatted message or None if conversion fails
    """
    try:
        # Skip SystemMessage - Acontext only supports 'user' and 'assistant' roles
        if isinstance(message, SystemMessage):
            return None

        # Determine role based on message type
        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, (AIMessage, ToolMessage)):
            role = "assistant"
        else:
            return None

        parts: List[Dict[str, Any]] = []

        # Handle ToolMessage specially - convert to tool-result part
        if isinstance(message, ToolMessage):
            # Safely convert content to string
            content = message.content
            if isinstance(content, (dict, list)):
                import json

                content_str = json.dumps(content, default=str)
            else:
                content_str = str(content) if content else ""

            if content_str.strip():
                parts.append(
                    {
                        "type": "tool-result",
                        "text": content_str,
                        "meta": {
                            "tool_call_id": getattr(message, "tool_call_id", None)
                        },
                    }
                )
        else:
            # Handle regular message content
            if message.content:
                # Handle content that might be a list (multi-modal)
                if isinstance(message.content, list):
                    for item in message.content:
                        if isinstance(item, str) and item.strip():
                            parts.append({"type": "text", "text": item})
                        elif isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            if text.strip():
                                parts.append({"type": "text", "text": text})
                elif isinstance(message.content, str) and message.content.strip():
                    parts.append({"type": "text", "text": message.content})

            # Handle tool calls for AIMessage
            if (
                isinstance(message, AIMessage)
                and hasattr(message, "tool_calls")
                and message.tool_calls
            ):
                for tool_call in message.tool_calls:
                    parts.append(
                        {
                            "type": "tool-call",
                            "text": tool_call.get("name", "unknown_tool"),
                            "meta": {
                                "name": tool_call.get("name", "unknown_tool"),
                                "arguments": tool_call.get("args", {}),
                            },
                        }
                    )

        if not parts:
            return None

        return {"role": role, "parts": parts}
    except Exception as e:
        logger.warning(f"Failed to convert message to Acontext format: {e}")
        return None


def create_acontext_capture_node(subagent_name: str) -> HookType:
    """Create a node that captures all messages and sends to Acontext.

    This node should be added to end_graph_hooks. It:
    1. Gets the Acontext client and space for this subagent
    2. Creates a session
    3. Sends all messages from the execution
    4. Flushes the session to extract skills

    Args:
        subagent_name: Name of the subagent for space identification

    Returns:
        Async node function for use in end_graph_hooks
    """

    async def acontext_capture_node(
        state: State, config: RunnableConfig, store: BaseStore
    ) -> State:
        """Capture all messages and send to Acontext for skill learning."""

        if not settings.ACONTEXT_ENABLED:
            return state

        try:
            client = await get_acontext_client()
            if not client:
                return state

            space_id = await get_subagent_space(subagent_name)
            if not space_id:
                return state

            # Get conversation_id from config for session caching
            configurable = config.get("configurable", {})
            conversation_id = configurable.get("thread_id", "default")

            # Get or create session for this conversation (same conversation_id = same session)
            session_id = get_subagent_session(subagent_name, conversation_id, space_id)
            if not session_id:
                return state

            logger.debug(
                f"Using Acontext session for '{subagent_name}' conversation '{conversation_id}': {session_id}"
            )

            messages = state.get("messages", [])
            sent_count = 0

            for message in messages:
                acontext_msg = _convert_message_to_acontext(message)
                if acontext_msg:
                    client.sessions.store_message(
                        session_id=session_id, blob=acontext_msg, format="acontext"
                    )
                    sent_count += 1

            client.sessions.flush(session_id)

            tasks_response = client.sessions.get_tasks(session_id)
            logger.info(
                f"Acontext: '{subagent_name}' - sent {sent_count} messages, "
                f"extracted {len(tasks_response.items)} tasks"
            )

        except Exception as e:
            logger.warning(f"Acontext capture failed for '{subagent_name}': {e}")

        return state

    return acontext_capture_node
