from enum import Enum
from typing import Union

from pydantic import BaseModel
from typing_extensions import TypedDict

from app.models.message_models import FileData, ReplyToMessageData, SelectedWorkflowData


class ImageData(BaseModel):
    """Generated-image metadata attached to a chat message."""

    url: str
    prompt: str
    improved_prompt: str | None = None


class ToolDataEntry(TypedDict):
    """Unified structure for tool execution data."""

    tool_name: str
    data: Union[dict, list, str, int, float, bool]
    timestamp: str | None


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
    "goal_data",
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
    metadata: dict | None = None
    replyToMessage: ReplyToMessageData | None = None


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
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
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
    {ConversationSource.WEB, ConversationSource.MOBILE}
)
BOT_CONVERSATION_SOURCES: frozenset[ConversationSource] = frozenset(
    {
        ConversationSource.WHATSAPP,
        ConversationSource.TELEGRAM,
        ConversationSource.DISCORD,
        ConversationSource.SLACK,
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
