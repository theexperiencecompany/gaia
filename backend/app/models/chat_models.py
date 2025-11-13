from enum import Enum
from typing import List, Optional, Union

from app.models.message_models import FileData, SelectedWorkflowData
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class ImageData(BaseModel):
    url: str
    prompt: str
    improved_prompt: Optional[str] = None


class IntegrationConnectionData(BaseModel):
    """Data structure for integration connection prompts."""

    integration_id: str
    integration_name: str
    integration_description: str
    integration_category: str
    message: str
    connect_url: str
    settings_url: Optional[str] = None


class SupportTicketData(BaseModel):
    """Data structure for support ticket creation."""

    type: str = Field(
        ..., description="Type of support request: 'support' or 'feature'"
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Brief title of the issue or request",
    )
    description: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description="Detailed description of the issue or request",
    )
    user_name: Optional[str] = Field(None, description="Name of the user")
    user_email: Optional[str] = Field(None, description="Email of the user")


class ToolDataEntry(TypedDict):
    """Unified structure for tool execution data."""

    tool_name: str
    data: Union[dict, List, str, int, float, bool]
    timestamp: Optional[str]


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
]


class MessageModel(BaseModel):
    type: str
    response: str
    date: Optional[str] = None
    image_data: Optional[ImageData] = None
    disclaimer: Optional[str] = None
    subtype: Optional[str] = None
    file: Optional[bytes] = None
    filename: Optional[str] = None
    filetype: Optional[str] = None
    message_id: Optional[str] = None
    fileIds: Optional[List[str]] = []
    fileData: Optional[List[FileData]] = []
    selectedTool: Optional[str] = None
    toolCategory: Optional[str] = None
    selectedWorkflow: Optional[SelectedWorkflowData] = None
    tool_data: Optional[List[ToolDataEntry]] = None
    follow_up_actions: Optional[List[str]] = None
    integration_connection_required: Optional[IntegrationConnectionData] = None
    metadata: Optional[dict] = None


class SystemPurpose(str, Enum):
    EMAIL_PROCESSING = "email_processing"
    REMINDER_PROCESSING = "reminder_processing"
    WORKFLOW_EXECUTION = "workflow_execution"
    OTHER = "other"


class ConversationModel(BaseModel):
    conversation_id: str
    description: str = "New Chat"
    is_system_generated: Optional[bool] = False
    system_purpose: Optional[SystemPurpose] = None


class UpdateMessagesRequest(BaseModel):
    conversation_id: str
    messages: List[MessageModel]


class StarredUpdate(BaseModel):
    starred: bool


class PinnedUpdate(BaseModel):
    pinned: bool


class UpdateDescriptionRequest(BaseModel):
    description: str


class ConversationSyncItem(BaseModel):
    conversation_id: str
    last_updated: Optional[str] = None


class BatchSyncRequest(BaseModel):
    conversations: List[ConversationSyncItem]
