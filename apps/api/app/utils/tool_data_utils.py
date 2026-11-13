"""Utility functions for converting legacy tool data to unified format."""

from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from app.models.chat_models import ToolDataEntry, tool_fields


class _StoredMessageToolData(BaseModel):
    """A stored message's unified tool_data, read verbatim.

    object on purpose: this runs in a mode="before" validator, ahead of
    MessageModel validating the entries themselves.
    """

    model_config = ConfigDict(extra="ignore")

    tool_data: object = None


def convert_legacy_tool_data(message: Mapping[str, object]) -> dict[str, object]:
    """Convert legacy individual tool fields to the unified tool_data array format.

    Backward compatibility for a message dict from the database that may
    still carry legacy tool fields.
    """
    # Create a copy to avoid modifying original
    converted_message = dict(message)
    tool_data_entries: list[object] = []
    timestamp = datetime.now(UTC).isoformat()

    # Check if message already has unified tool_data - preserve it
    existing_tool_data = _StoredMessageToolData.model_validate(message).tool_data
    if isinstance(existing_tool_data, list) and existing_tool_data:
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
