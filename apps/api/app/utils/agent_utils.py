import json
from datetime import datetime, timezone
from typing import List, Optional, cast
from uuid import uuid4

from langchain_core.messages import ToolCall

from app.config.loggers import llm_logger as logger
from app.models.chat_models import (
    MessageModel,
    ToolDataEntry,
    UpdateMessagesRequest,
    tool_fields,
)
from app.services.conversation_service import update_messages
from app.agents.tools.core.registry import get_tool_registry


async def format_tool_progress(tool_call: ToolCall) -> Optional[dict]:
    """Format tool execution progress data for streaming UI updates.

    Transforms a LangChain ToolCall object into a structured progress update
    that can be displayed in the frontend. Extracts tool name, formats it for
    display, and retrieves the tool category from the registry.

    Args:
        tool_call: LangChain ToolCall object containing tool execution details

    Returns:
        Dictionary with progress information including formatted message,
        tool name, category, and show_category flag, or None if tool name is missing
    """

    tool_registry = await get_tool_registry()
    tool_name_raw = tool_call.get("name")
    if not tool_name_raw:
        return None

    # Tools that emit their own progress messages - skip generic emission
    if tool_name_raw == "handoff":
        return None

    # Special tools with custom display names and hidden categories
    # Format: (category, display_name) - these tools don't show category text
    special_tools = {
        "retrieve_tools": ("retrieve_tools", "Retrieving tools"),
        "call_executor": ("executor", "Delegating to executor"),
    }

    if tool_name_raw in special_tools:
        tool_category, tool_display_name = special_tools[tool_name_raw]
        show_category = False
    else:
        tool_category = tool_registry.get_category_of_tool(tool_name_raw)
        tool_display_name = tool_name_raw.replace("_", " ").title()
        show_category = True

        # Extract integration name from MCP categories (e.g., "mcp_perplexity_6947dd82..." -> "perplexity")
        if tool_category and tool_category.startswith("mcp_"):
            parts = tool_category.split("_")
            if len(parts) >= 2:
                tool_category = parts[1]

    return {
        "progress": {
            "message": tool_display_name,
            "tool_name": tool_name_raw,
            "tool_category": tool_category,
            "show_category": show_category,
        }
    }


def format_sse_response(content: str) -> str:
    """Format text content as Server-Sent Events (SSE) response.

    Wraps content in the standard SSE data format with JSON encoding
    for transmission to frontend clients via EventSource connections.

    Args:
        content: Text content to be streamed to the client

    Returns:
        SSE-formatted string with 'data:' prefix and proper line endings
    """
    return f"data: {json.dumps({'response': content})}\n\n"


def format_sse_data(data: dict) -> str:
    """Format structured data as Server-Sent Events (SSE) response.

    Converts dictionary data to JSON and wraps it in SSE format for
    streaming structured information like tool progress, errors, or
    custom events to frontend clients.

    Args:
        data: Dictionary containing structured data to stream

    Returns:
        SSE-formatted string with JSON-encoded data and proper line endings
    """
    return f"data: {json.dumps(data)}\n\n"


def process_custom_event_for_tools(payload) -> dict:
    """Extract and process tool execution data from custom LangGraph events.

    Safely processes custom event payloads from LangGraph streams to extract
    tool execution results and data. Handles serialization and delegates to
    the chat service for tool-specific data extraction.

    Args:
        payload: Raw event payload from LangGraph custom events

    Returns:
        Dictionary containing extracted tool data, or empty dict if
        extraction fails or no data is available
    """
    try:
        # Import inside function to avoid circular imports
        from app.services.chat_service import extract_tool_data

        serialized = json.dumps(payload) if payload else "{}"
        new_data = extract_tool_data(serialized)
        return new_data if new_data else {}
    except Exception as e:
        logger.error(f"Error extracting tool data: {e}")
        return {}


async def store_agent_progress(
    conversation_id: str, user_id: str, current_message: str, current_tool_data: dict
) -> None:
    """Store agent execution progress in real-time.

    Generic function for storing bot messages during agent execution.
    Works for any agent execution - workflows, normal chat, etc.
    Only stores messages that have meaningful content (message text or tool data).

    Args:
        conversation_id: Conversation ID for storage
        user_id: User ID for authorization
        current_message: Current accumulated LLM response
        current_tool_data: Current accumulated tool outputs (can contain both unified tool_data and legacy individual fields)
    """
    try:
        # Check if there's meaningful content
        has_tool_data = False
        if current_tool_data:
            # Check for unified tool_data format
            if "tool_data" in current_tool_data and current_tool_data["tool_data"]:
                has_tool_data = True
            # Check for any other tool data keys (legacy individual fields)
            elif any(current_tool_data.values()):
                has_tool_data = True

        has_content = current_message.strip() or has_tool_data

        if not has_content:
            return  # Skip storing empty messages

        # Create bot message using same pattern as chat_service.py
        bot_message = MessageModel(
            type="bot",
            response=current_message,
            date=datetime.now(timezone.utc).isoformat(),
            message_id=str(uuid4()),
        )

        # Handle tool data in unified format
        if current_tool_data:
            # If we have unified tool_data, use it directly
            if "tool_data" in current_tool_data:
                bot_message.tool_data = current_tool_data["tool_data"]
            else:
                # Legacy support: convert individual fields to unified format
                tool_data_entries = []
                timestamp = datetime.now(timezone.utc).isoformat()

                # Convert individual tool fields to unified ToolDataEntry format using tool_fields list
                for field_name in tool_fields:
                    if (
                        field_name in current_tool_data
                        and current_tool_data[field_name] is not None
                    ):
                        tool_entry = {
                            "tool_name": field_name,
                            "data": current_tool_data[field_name],
                            "timestamp": timestamp,
                        }
                        tool_data_entries.append(tool_entry)

                if tool_data_entries:
                    bot_message.tool_data = cast(List[ToolDataEntry], tool_data_entries)

            # Handle follow_up_actions separately (it's a core field, not tool data)
            if "follow_up_actions" in current_tool_data:
                bot_message.follow_up_actions = current_tool_data["follow_up_actions"]

        # Store immediately using existing service
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[bot_message],
            ),
            user={"user_id": user_id},
        )

    except Exception as e:
        # Don't break agent execution for storage failures
        logger.error(f"Failed to store agent progress: {str(e)}")
