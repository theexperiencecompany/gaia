from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints
from typing_extensions import TypedDict

from app.services.storage import SAFE_PATH_ID_PATTERN

SafePathId = Annotated[str, StringConstraints(pattern=SAFE_PATH_ID_PATTERN)]


class MessageDict(TypedDict):
    """One chat turn as {role, content} for LLM history payloads."""

    role: str
    content: str


class FileData(BaseModel):
    """Uploaded-file reference attached to a chat message."""

    fileId: str
    url: str
    filename: str
    type: str | None = "file"
    message: str | None = "File uploaded successfully"
    # Server-owned summary of the file's content. Populated from MongoDB on the
    # agent path and on the upload response; never trusted from inbound requests.
    description: str | None = None


class SelectedWorkflowData(BaseModel):
    """Workflow the user attached to a message for execution."""

    id: str
    title: str
    description: str
    prompt: str | None = None
    steps: list[dict[str, Any]]


class SelectedCalendarEventData(BaseModel):
    """Calendar event the user attached to a message."""

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
    """Chat-stream request carrying the full message history and attachments."""

    message: str
    conversation_id: SafePathId | None = None
    messages: list[MessageDict]
    fileIds: list[str] | None = []
    fileData: list[FileData] | None = []
    selectedTool: str | None = None
    toolCategory: str | None = None
    selectedWorkflow: SelectedWorkflowData | None = None
    selectedCalendarEvent: SelectedCalendarEventData | None = None
    replyToMessage: ReplyToMessageData | None = None
    is_onboarding_demo: bool = False
    # Voice sessions set this so the stream holds open until a delegated
    # executor delivers its narrated answer (pushed as a `voice_tts` SSE frame
    # for the voice agent to speak). Text clients leave it False — the executor
    # result reaches them out-of-band over the WebSocket as today.
    voice_mode: bool = False


class MessageRequest(BaseModel):
    """Minimal chat request with a single message."""

    message: str
