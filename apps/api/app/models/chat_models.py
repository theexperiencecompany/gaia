from enum import Enum, StrEnum

from pydantic import BaseModel

# The channel vocabulary lives in app.constants.chat, a leaf, so
# app.constants.outbound can derive the outbound queue set without the model
# stack. Re-exported here because this is the import site consumers use.
from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource, SourceCategory

# ToolDataEntry lives in app.models.tool_data_models, which imports nothing heavy, so the
# pure conversation core can use it without booting settings. Re-exported here for the
# same reason as ConversationSource above.
from app.models.tool_data_models import ToolDataEntry

__all__ = [
    "BOT_CONVERSATION_SOURCES",
    "BatchSyncRequest",
    "ConversationModel",
    "ConversationSource",
    "ConversationSyncItem",
    "ImageData",
    "PinnedUpdate",
    "SourceCategory",
    "StarredUpdate",
    "SystemPurpose",
    "ToolDataEntry",
    "UpdateDescriptionRequest",
]


class ImageData(BaseModel):
    """Generated-image metadata attached to a chat message."""

    url: str
    prompt: str
    improved_prompt: str | None = None


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


class SystemPurpose(str, Enum):
    """Why a system-generated conversation was created."""

    EMAIL_PROCESSING = "email_processing"
    REMINDER_PROCESSING = "reminder_processing"
    WORKFLOW_EXECUTION = "workflow_execution"
    #: The seeded Getting-started thread: the user's first screen after onboarding.
    GETTING_STARTED = "getting_started"
    OTHER = "other"


class ConversationModel(BaseModel):
    """A conversation to create: its id and the display/system metadata it starts with."""

    conversation_id: str
    description: str = "New Chat"
    is_system_generated: bool | None = False
    system_purpose: SystemPurpose | None = None
    is_unread: bool | None = False
    source: ConversationSource | None = None
    is_onboarding_demo: bool = False


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
