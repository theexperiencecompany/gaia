"""The old message shapes the entries migration reads, and only it.

A conversation once embedded its messages in the head as one array of MessageModel dicts. The
migration and its verify oracle read that array; the running app knows only the conversation log.
These models go when the migration does.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.chat_models import ReactionBy, tool_fields
from app.models.conversation_log_models import ConversationState
from app.models.conversation_models import MessageShape
from app.models.message_models import (
    FileData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.todo_wake_models import TodoRunWake
from shared.py.conversation_wire import ImageData, ReplyToMessageData, ToolDataEntry

#: MessageModel.type of a message the human wrote, and of one GAIA wrote.
USER_MESSAGE_TYPE = "user"
BOT_MESSAGE_TYPE = "bot"


class MessageReaction(BaseModel):
    """GAIA's one emoji reaction on a user message."""

    emoji: str
    by: ReactionBy


class MessageModel(BaseModel):
    """One element of the old embedded messages array: a message with its content, attachments and tool data."""

    type: str
    response: str
    date: str | None = None
    image_data: ImageData | None = None
    disclaimer: str | None = None
    subtype: str | None = None
    file: bytes | None = None
    filename: str | None = None
    filetype: str | None = None
    message_id: str | None = None
    fileIds: list[str] | None = []
    fileData: list[FileData] | None = []
    selectedTool: str | None = None
    toolCategory: str | None = None
    selectedWorkflow: SelectedWorkflowData | None = None
    selectedCalendarEvent: SelectedCalendarEventData | None = None
    todo_run_wake: TodoRunWake | None = None
    tool_data: list[ToolDataEntry] | None = None
    follow_up_actions: list[str] | None = None
    metadata: dict[str, object] | None = None
    replyToMessage: ReplyToMessageData | None = None
    error: str | None = None
    stopped: bool | None = None
    in_progress: bool | None = None
    pinned: bool | None = None
    reaction: MessageReaction | None = None
    platform_message_id: str | None = None
    first_contact: bool | None = None


class _StoredMessageToolData(BaseModel):
    """A stored message's unified tool_data, read verbatim, ahead of MessageModel validating its entries."""

    model_config = ConfigDict(extra="ignore")

    tool_data: object = None


def convert_legacy_tool_data(message: Mapping[str, object]) -> dict[str, object]:
    """Move an old message's per-tool fields into its unified tool_data array."""
    converted_message = dict(message)
    tool_data_entries: list[object] = []
    timestamp = datetime.now(UTC).isoformat()
    existing_tool_data = _StoredMessageToolData.model_validate(message).tool_data
    if isinstance(existing_tool_data, list) and existing_tool_data:
        tool_data_entries.extend(existing_tool_data)
        del converted_message["tool_data"]
    for field_name in tool_fields:
        if converted_message.get(field_name) is not None:
            tool_entry: ToolDataEntry = {
                "tool_name": field_name,
                "data": converted_message[field_name],
                "timestamp": timestamp,
            }
            tool_data_entries.append(tool_entry)
            del converted_message[field_name]
    if tool_data_entries:
        converted_message["tool_data"] = tool_data_entries
    return converted_message


class ConversationEntry(MessageModel):
    """One old-shape message with the seq the log holds it at: order is seq, never a date."""

    seq: int

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return convert_legacy_tool_data(value) if isinstance(value, dict) else value


class LegacyShape(MessageShape):
    """An old message's identifying fields, beside the log fields every stored entry has."""

    type: str | None = None
    response: str | None = None
    date: object = None
    message_id: str | None = None
    reacts_to_message_id: str | None = None


class NotKeptFields(BaseModel):
    """Old message fields no client renders, so the log keeps them nowhere."""

    model_config = ConfigDict(extra="ignore")

    disclaimer: object = None
    subtype: object = None
    file: object = None
    filename: object = None
    filetype: object = None
    metadata: object = None

    def carried(self) -> bool:
        return any(value is not None for value in self.model_dump().values())


class LegacyMessage(BaseModel):
    """One element of the embedded messages array, in whatever shape the old build wrote."""

    model_config = ConfigDict(extra="allow")

    message_id: str | None = None
    date: object = None

    def stored(self) -> dict[str, object]:
        """Return the element exactly as it is stored in the array."""
        return self.model_dump(exclude_unset=True)


class EmbeddedHead(BaseModel):
    """A head as the entries migration reads it: the old embedded array, its fingerprint, and the log."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    user_id: str
    source: str | None = None
    log_head: int | None = None
    state: ConversationState | None = None
    messages: list[LegacyMessage] = Field(default_factory=list)
    migrated_fingerprint: int | None = None
    fingerprint: int = Field(alias="_fingerprint")


class HeadRefRow(BaseModel):
    """A head as a migration scan lists it: its _id as text, and identity."""

    model_config = ConfigDict(extra="forbid")

    head_id: str
    conversation_id: str
    user_id: str
