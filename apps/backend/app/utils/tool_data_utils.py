"""
Utility functions for converting legacy tool data to unified format.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from app.models.chat_models import ToolDataEntry, tool_fields


def convert_legacy_tool_data(message: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert legacy individual tool fields to unified tool_data array format.

    This function handles backward compatibility by detecting legacy tool fields
    and converting them into the new ToolDataEntry array structure.

    Args:
        message: Raw message dict from database that may contain legacy tool fields

    Returns:
        Dict with legacy fields converted to unified tool_data format
    """
    # Create a copy to avoid modifying original
    converted_message = message.copy()
    tool_data_entries = []
    timestamp = datetime.now(timezone.utc).isoformat()

    # Check if message already has unified tool_data - preserve it
    existing_tool_data = converted_message.get("tool_data", [])
    if existing_tool_data:
        tool_data_entries.extend(existing_tool_data)
        # Remove from message to avoid double processing
        del converted_message["tool_data"]

    # Convert legacy fields to unified format using the dynamic tool_fields list
    # Exclude 'tool_data' itself since it's the unified format, not a legacy field
    for field_name in tool_fields:
        if (
            field_name != "tool_data"
            and field_name in converted_message
            and converted_message[field_name] is not None
        ):
            # Create ToolDataEntry
            tool_entry: ToolDataEntry = {
                "tool_name": field_name,
                "data": converted_message[field_name],
                "timestamp": timestamp,
            }
            tool_data_entries.append(tool_entry)

            # Remove the legacy field
            del converted_message[field_name]

    # Set unified tool_data if we have any entries
    if tool_data_entries:
        converted_message["tool_data"] = tool_data_entries

    return converted_message


def convert_conversation_messages(conversation: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert all messages in a conversation from legacy format to unified tool_data format.

    Args:
        conversation: Conversation document from database

    Returns:
        Conversation with all messages converted to unified format
    """
    if "messages" not in conversation:
        return conversation

    conversation = conversation.copy()
    converted_messages = []

    for message in conversation["messages"]:
        converted_message = convert_legacy_tool_data(message)
        converted_messages.append(converted_message)

    conversation["messages"] = converted_messages
    return conversation
