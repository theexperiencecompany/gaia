from enum import Enum, StrEnum
from typing import Any, NotRequired

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

# The channel vocabulary lives in app.constants.chat, a leaf, so
# app.constants.outbound can derive the outbound queue set without the model
# stack. Re-exported here because this is the import site consumers use.
from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource, SourceCategory
from app.models.message_models import FileData, ReplyToMessageData, SelectedWorkflowData

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


class ToolDataEntry(TypedDict):
    """Unified structure for tool execution data.

    Every key an emitter can stamp must be declared here. This TypedDict is the
    element type of ``MessageModel.tool_data``, and Pydantic drops undeclared
    keys on ``model_dump()`` — which is how a message reaches Mongo. An emitted
    key missing from this shape therefore survives the live SSE frame (the
    frontend parses those against its own loose schema) and silently vanishes
    from the stored turn, so the bug only ever appears on reload.

    ``data`` is deliberately open: every tool owns the shape it puts here (a
    calendar option list, an email thread, a rendered artifact), so the only
    honest constraint is "JSON the frontend's per-tool card knows how to read".
    Everything around it is closed.

    The frontend mirror is ``ToolDataEntrySchema`` in
    ``libs/shared/ts/src/chat/schema.ts``.
    """

    tool_name: str
    # Any on purpose (see above): it is JSON the tool owns, and the generated
    # TypeScript reads it as `unknown` — the honest type for every consumer to
    # narrow from.
    data: Any
    # Optional: emitters always stamp it, but legacy stored entries predate the
    # field, so a read must tolerate its absence rather than fail validation.
    timestamp: NotRequired[str | None]
    # Which card renders the entry, stamped by format_tool_call_entry, the HIL
    # frame, the reasoning absorber and rate-limit/artifact emitters; absent on
    # plain per-tool-field entries, which the frontend keys off tool_name alone.
    tool_category: NotRequired[str]
    # Tags an entry produced inside a delegated subagent, so
    # reconstruct_subagent_groups can fold it into that subagent's group.
    subagent_id: NotRequired[str]
    # MCP App UI metadata (resource_uri, csp, permissions) and the server that
    # serves it. Only tool_calls_data entries for MCP tools carry these; without
    # them a restored turn cannot re-fetch the iframe.
    mcp_ui: NotRequired[dict[str, Any] | None]
    mcp_server_url: NotRequired[str | None]


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


class MessageKind(StrEnum):
    """What a bot message IS beyond its text, set when comms' intent is known at
    creation and would otherwise be unrecoverable from the body alone (a deliberate
    one-emoji acknowledgement reads identically to a coincidental one-emoji reply)."""

    TEXT = "text"
    EMOJI_ACK = "emoji_ack"  # comms acknowledged a background update with a single emoji


class MessageModel(BaseModel):
    """A single chat message with its content, attachments and tool data."""

    type: str
    response: str
    kind: MessageKind = MessageKind.TEXT
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
    tool_data: list[ToolDataEntry] | None = None
    follow_up_actions: list[str] | None = None
    metadata: dict[str, Any] | None = None
    replyToMessage: ReplyToMessageData | None = None
    # Terminal stream error for a bot turn that produced no response — rendered
    # on reload instead of an empty bubble.
    error: str | None = None
    # Set by the pin-message endpoint on the embedded message; absent on most
    # messages, so it reads back as None unless the user pinned this one.
    pinned: bool | None = None
    # GAIA id of the message an emoji-ack reacts to. Set only when kind is
    # EMOJI_ACK; the web client renders the emoji as a reaction badge on this
    # message instead of a new bubble. None everywhere else.
    reacts_to_message_id: str | None = None
    # Platform-native id (WhatsApp wamid, Telegram message_id, Discord id, Slack
    # ts). Set only on user messages that arrived through a bot, so a later
    # background reaction can anchor to the exact platform message. Else None.
    platform_message_id: str | None = None


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
