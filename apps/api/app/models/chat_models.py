from enum import Enum, StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# The channel vocabulary lives in app.constants.chat, a leaf, so
# app.constants.outbound can derive the outbound queue set without the model
# stack. Re-exported here because this is the import site consumers use.
from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource, SourceCategory
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.todo_wake_models import TodoRunWake

# ToolDataEntry lives in app.models.tool_data_models, which imports nothing heavy, so the
# pure conversation core can use it without booting settings. Re-exported here for the
# same reason as ConversationSource above.
from app.models.tool_data_models import ToolDataEntry

__all__ = [
    "BOT_CONVERSATION_SOURCES",
    "BatchSyncRequest",
    "CancelStreamResponse",
    "ConversationModel",
    "ConversationSource",
    "ConversationSyncItem",
    "ImageData",
    "MessageModel",
    "PinnedUpdate",
    "SourceCategory",
    "StarredUpdate",
    "SystemPurpose",
    "ToolDataEntry",
    "UpdateDescriptionRequest",
    "UpdateMessagesRequest",
]


class ImageData(BaseModel):
    """Generated-image metadata attached to a chat message."""

    url: str
    prompt: str
    improved_prompt: str | None = None


class SavedSubagentGroup(BaseModel):
    """The parts of a saved subagent_group entry's data a resumed run extends in place."""

    model_config = ConfigDict(extra="ignore")

    subagent_id: str = ""
    tool_calls: list[dict[str, object]] = Field(default_factory=list)
    completed_at: str | None = None
    duration_ms: int | None = None


tool_fields = [
    "calendar_options",
    "calendar_delete_options",
    "calendar_edit_options",
    "email_compose_data",
    "email_fetch_data",
    "email_thread_data",
    "email_sent_data",
    "contacts_data",
    "people_search_data",
    "support_ticket_data",
    "calendar_fetch_data",
    "calendar_list_fetch_data",
    "weather_data",
    "search_results",
    "deep_research_results",
    "notification_data",
    "send_notification_data",
    "memory_data",
    "todo_data",
    "code_data",
    "google_docs_data",
    "integration_connection_required",
    "connect_options",
    "integration_list_data",
    "device_onboarding_required",
    "device_approval_required",
    "reddit_data",
    "twitter_user_data",
    "twitter_search_data",
    "workflow_draft",
    "workflow_created",
    "artifact_data",
    "screenshot_data",
    "browser_task_data",
    "mcp_app",
]


class ReactionBy(StrEnum):
    """Which mind put a reaction on a message: the instant classifier or the chat model."""

    JEV = "jev"
    CHAT_MODEL = "chat_model"


class MessageReaction(BaseModel):
    """GAIA's one emoji reaction on a user message."""

    emoji: str
    by: ReactionBy


class MessageModel(BaseModel):
    """A single chat message with its content, attachments and tool data."""

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
    # What woke a tracked todo's run, on the user's side of the todo's chat.
    todo_run_wake: TodoRunWake | None = None
    tool_data: list[ToolDataEntry] | None = None
    follow_up_actions: list[str] | None = None
    metadata: dict[str, Any] | None = None
    replyToMessage: ReplyToMessageData | None = None
    # Terminal stream error for a bot turn that produced no response — rendered
    # on reload instead of an empty bubble.
    error: str | None = None
    # True on a bot turn the user stopped with Stop; the client shows a quiet
    # "Stopped" line under it. None everywhere else.
    stopped: bool | None = None
    # True on a bot reply whose entry holds its place in the order (opened when the
    # user first saw it) while its turn is still running. None once the turn saves it.
    in_progress: bool | None = None
    # Set by the pin-message endpoint on the embedded message; absent on most
    # messages, so it reads back as None unless the user pinned this one.
    pinned: bool | None = None
    # Set only on a user message GAIA reacted to; one reaction per message.
    reaction: MessageReaction | None = None
    # Platform-native id (WhatsApp wamid, Telegram message_id, Discord id, Slack
    # ts). Set only on user messages that arrived through a bot, so a later
    # background reaction can anchor to the exact platform message. Else None.
    platform_message_id: str | None = None
    # Set on the user's linking message stored at account linking: no chat turn
    # ran for it, so no chat:message_submitted counts it. None everywhere else.
    first_contact: bool | None = None


class SystemPurpose(str, Enum):
    """Why a system-generated conversation was created."""

    EMAIL_PROCESSING = "email_processing"
    REMINDER_PROCESSING = "reminder_processing"
    WORKFLOW_EXECUTION = "workflow_execution"
    #: The seeded Getting-started thread: the user's first screen after onboarding.
    GETTING_STARTED = "getting_started"
    OTHER = "other"


class ConversationModel(BaseModel):
    """A chat conversation and its display/system metadata."""

    conversation_id: str
    description: str = "New Chat"
    is_system_generated: bool | None = False
    system_purpose: SystemPurpose | None = None
    is_unread: bool | None = False
    source: ConversationSource | None = None
    is_onboarding_demo: bool = False


class UpdateMessagesRequest(BaseModel):
    """Request to replace the messages of a conversation."""

    conversation_id: str
    messages: list[MessageModel]


class StarredUpdate(BaseModel):
    """Request to set a conversation's starred flag."""

    starred: bool


class PinnedUpdate(BaseModel):
    """Request to set a conversation's pinned flag."""

    pinned: bool


class UpdateDescriptionRequest(BaseModel):
    """Request to rename a conversation's description."""

    description: str


class ConversationSyncItem(BaseModel):
    """A conversation id and its last-updated timestamp for client sync."""

    conversation_id: str
    last_updated: str | None = None


class BatchSyncRequest(BaseModel):
    """Batch of conversation sync items sent by a client to reconcile state."""

    conversations: list[ConversationSyncItem]


class CancelStreamResponse(BaseModel):
    """Outcome of a stream-cancellation request.

    ``error`` is set only when the stream could not be cancelled at all (it was
    never started, or already expired from Redis).
    """

    success: bool
    stream_id: str
    error: str | None = None
