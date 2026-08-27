from enum import Enum
from typing import Any, NotRequired, Union

from pydantic import BaseModel
from typing_extensions import TypedDict

from app.models.message_models import FileData, ReplyToMessageData, SelectedWorkflowData


class ImageData(BaseModel):
    """Generated-image metadata attached to a chat message."""

    url: str
    prompt: str
    improved_prompt: str | None = None


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
    data: Union[dict[str, Any], list[Any], str, int, float, bool]
    # Optional: emitters always stamp it, but legacy stored entries predate the
    # field, so a read must tolerate its absence rather than fail validation.
    timestamp: NotRequired[str | None]
    # Which card renders the entry. Stamped by format_tool_call_entry, the HIL
    # approval frame, the reasoning absorber, and the artifact/rate-limit
    # emitters; absent on the plain per-tool-field entries normalize_custom_event
    # builds, which the frontend keys off tool_name alone.
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
    "integration_list_data",
    "reddit_data",
    "twitter_user_data",
    "twitter_search_data",
    "workflow_draft",
    "workflow_created",
    "artifact_data",
    "screenshot_data",
    "mcp_app",
]


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


class SystemPurpose(str, Enum):
    """Why a system-generated conversation was created."""

    EMAIL_PROCESSING = "email_processing"
    REMINDER_PROCESSING = "reminder_processing"
    WORKFLOW_EXECUTION = "workflow_execution"
    OTHER = "other"


class ConversationSource(str, Enum):
    """Client or channel a conversation originated from."""

    WEB = "web"
    MOBILE = "mobile"
    DESKTOP = "desktop"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    IMESSAGE = "imessage"
    WORKFLOW_SYSTEM = "workflow_system"
    BACKGROUND = "background"

    @classmethod
    def coerce(cls, value: "ConversationSource | str | None") -> "ConversationSource | None":
        """Parse a raw source value (e.g. a stored string) into the enum.

        Returns None for blank or unrecognised values so callers can compare on
        enum members instead of raw strings.
        """
        if value is None or isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            return None


class SourceCategory(str, Enum):
    """Generalized origin of a graph invocation.

    Coarser than ``ConversationSource``: every specific channel rolls up to one
    of these so traces and tools can branch on "where did this run come from"
    without enumerating every platform.
    """

    BG = "bg"  # autonomous background work (workflows, scheduled todos, sweeps)
    UI = "ui"  # first-party clients (web, mobile, desktop)
    BOT = "bot"  # messaging-platform bots (whatsapp, telegram, discord, slack)

    @classmethod
    def from_source(cls, source: "ConversationSource | str | None") -> "SourceCategory":
        """Map a specific ``ConversationSource`` to its category.

        Unknown / unset sources fall back to ``BG`` — the only callers that
        leave the source blank are the silent background paths.
        """
        channel = ConversationSource.coerce(source)
        if channel in _UI_SOURCES:
            return cls.UI
        if channel in BOT_CONVERSATION_SOURCES:
            return cls.BOT
        return cls.BG


# Specific channels that belong to each generalized category. Single source of
# truth for "which conversation sources are messaging-platform bots" — reused by
# delivery routing and the web conversation-list filter. Members are enums so all
# comparisons happen on ConversationSource, never raw strings.
_UI_SOURCES: frozenset[ConversationSource] = frozenset(
    {ConversationSource.WEB, ConversationSource.MOBILE, ConversationSource.DESKTOP}
)
BOT_CONVERSATION_SOURCES: frozenset[ConversationSource] = frozenset(
    {
        ConversationSource.WHATSAPP,
        ConversationSource.TELEGRAM,
        ConversationSource.DISCORD,
        ConversationSource.SLACK,
        ConversationSource.IMESSAGE,
    }
)


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
