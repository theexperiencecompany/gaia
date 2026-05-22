from typing import Any

from pydantic import BaseModel
from typing_extensions import TypedDict


class MessageDict(TypedDict):
    role: str
    content: str


class FileData(BaseModel):
    fileId: str
    url: str
    filename: str
    type: str | None = "file"
    message: str | None = "File uploaded successfully"


class SelectedWorkflowData(BaseModel):
    id: str
    title: str
    description: str
    prompt: str | None = None
    steps: list[dict[str, Any]]


class SelectedCalendarEventData(BaseModel):
    id: str
    summary: str
    description: str
    start: dict[str, str | None]
    end: dict[str, str | None]
    calendarId: str | None = None
    calendarTitle: str | None = None
    backgroundColor: str | None = None
    isAllDay: bool | None = False


class ReplyToMessageData(BaseModel):
    """Data for the message being replied to."""

    id: str
    content: str
    role: str


class MessageRequestWithHistory(BaseModel):
    message: str
    conversation_id: str | None = None
    messages: list[MessageDict]
    fileIds: list[str] | None = []
    fileData: list[FileData] | None = []
    selectedTool: str | None = None
    toolCategory: str | None = None
    selectedWorkflow: SelectedWorkflowData | None = None
    selectedCalendarEvent: SelectedCalendarEventData | None = None
    replyToMessage: ReplyToMessageData | None = None  # Message being replied to
    is_onboarding_demo: bool = False


class MessageRequest(BaseModel):
    message: str


class MessageRequestPrimary(BaseModel):
    message: str
    conversation_id: str
