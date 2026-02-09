from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel
from typing_extensions import TypedDict

from app.models.message_models import FileData, ReplyToMessageData, SelectedWorkflowData


class ImageData(BaseModel):
    url: str
    prompt: str
    improved_prompt: Optional[str] = None


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
    "integration_list_data",
    "reddit_data",
    "twitter_user_data",
    "twitter_search_data",
    "workflow_draft",
    "workflow_created",
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
    metadata: Optional[dict] = None
    replyToMessage: Optional[ReplyToMessageData] = None


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
    is_unread: Optional[bool] = False


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
