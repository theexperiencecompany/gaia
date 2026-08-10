"""
Utility functions for converting legacy tool data to unified format.
"""

from datetime import UTC, datetime
from typing import cast

from app.models.chat_models import ToolDataEntry, tool_fields


def convert_legacy_tool_data(message: dict[str, object]) -> dict[str, object]:
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
    tool_data_entries: list[ToolDataEntry] = []
    timestamp = datetime.now(UTC).isoformat()

    # Check if message already has unified tool_data - preserve it
    existing_tool_data = converted_message.get("tool_data", [])
    if isinstance(existing_tool_data, list):
        tool_data_entries.extend(
            cast(ToolDataEntry, e) for e in existing_tool_data if isinstance(e, dict)
        )
        # Remove from message to avoid double processing
        converted_message.pop("tool_data", None)

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
                "data": cast(
                    dict[str, object] | list[object] | str | int | float | bool,
                    converted_message[field_name],
                ),
                "timestamp": timestamp,
            }
            tool_data_entries.append(tool_entry)

            # Remove the legacy field
            del converted_message[field_name]

    # Set unified tool_data if we have any entries
    if tool_data_entries:
        converted_message["tool_data"] = tool_data_entries

    return converted_message
