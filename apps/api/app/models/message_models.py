from typing import List, Optional, Dict, Any

from pydantic import BaseModel
from typing_extensions import TypedDict


class MessageDict(TypedDict):
    role: str
    content: str


class FileData(BaseModel):
    fileId: str
    url: str
    filename: str
    type: Optional[str] = "file"
    message: Optional[str] = "File uploaded successfully"


class SelectedWorkflowData(BaseModel):
    id: str
    title: str
    description: str
    steps: List[Dict[str, Any]]


class SelectedCalendarEventData(BaseModel):
    id: str
    summary: str
    description: str
    start: Dict[str, Optional[str]]
    end: Dict[str, Optional[str]]
    calendarId: Optional[str] = None
    calendarTitle: Optional[str] = None
    backgroundColor: Optional[str] = None
    isAllDay: Optional[bool] = False


class ReplyToMessageData(BaseModel):
    """Data for the message being replied to."""

    id: str  # Message ID being replied to
    content: str  # Preview of the message content (truncated)
    role: str  # "user" or "assistant"


class MessageRequestWithHistory(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    messages: List[MessageDict]
    fileIds: Optional[List[str]] = []
    fileData: Optional[List[FileData]] = []
    selectedTool: Optional[str] = None  # Tool selected via slash commands
    toolCategory: Optional[str] = None  # Category of the selected tool
    selectedWorkflow: Optional[SelectedWorkflowData] = (
        None  # Workflow selected for execution
    )
    selectedCalendarEvent: Optional[SelectedCalendarEventData] = (
        None  # Calendar event selected for context
    )
    replyToMessage: Optional[ReplyToMessageData] = None  # Message being replied to


class SaveIncompleteConversationRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    fileIds: Optional[List[str]] = []
    fileData: Optional[List[FileData]] = []
    selectedTool: Optional[str] = None
    toolCategory: Optional[str] = None
    selectedWorkflow: Optional[SelectedWorkflowData] = None
    selectedCalendarEvent: Optional[SelectedCalendarEventData] = None
    replyToMessage: Optional[ReplyToMessageData] = None
    incomplete_response: str = ""  # The partial response from the bot


class MessageRequest(BaseModel):
    message: str


class MessageRequestPrimary(BaseModel):
    message: str
    conversation_id: str
