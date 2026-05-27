from enum import Enum
from typing import Any, Union

from pydantic import BaseModel
from typing_extensions import TypedDict

from app.models.message_models import FileData, ReplyToMessageData, SelectedWorkflowData


class ImageData(BaseModel):
    url: str
    prompt: str
    improved_prompt: str | None = None


class MCPAppData(BaseModel):
    tool_call_id: str
    tool_name: str
    server_url: str
    resource_uri: str
    html_content: str
    csp: dict[str, Any] | None = None
    permissions: list[str] = []
    tool_result: Any | None = None
    tool_arguments: dict[str, Any] = {}


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
    "memory_data",
    "todo_data",
    "document_data",
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
    EMAIL_PROCESSING = "email_processing"
    REMINDER_PROCESSING = "reminder_processing"
    WORKFLOW_EXECUTION = "workflow_execution"
    OTHER = "other"


class ConversationSource(str, Enum):
    WEB = "web"
    MOBILE = "mobile"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    WORKFLOW_SYSTEM = "workflow_system"


class ConversationModel(BaseModel):
    conversation_id: str
    description: str = "New Chat"
    is_system_generated: bool | None = False
    system_purpose: SystemPurpose | None = None
    is_unread: bool | None = False
    source: ConversationSource | None = None
    is_onboarding_demo: bool = False


class UpdateMessagesRequest(BaseModel):
    conversation_id: str
    messages: list[MessageModel]


class StarredUpdate(BaseModel):
    starred: bool


class PinnedUpdate(BaseModel):
    pinned: bool


class UpdateDescriptionRequest(BaseModel):
    description: str


class ConversationSyncItem(BaseModel):
    conversation_id: str
    last_updated: str | None = None


class BatchSyncRequest(BaseModel):
    conversations: list[ConversationSyncItem]
