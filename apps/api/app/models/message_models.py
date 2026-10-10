from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import TypedDict

from app.constants.chat import MAX_MESSAGE_LENGTH
from app.constants.vfs import SAFE_PATH_ID_PATTERN
from app.models.calendar_models import GoogleCalendarEventDateTime
from app.models.workflow_models import WorkflowStep

SafePathId = Annotated[str, StringConstraints(pattern=SAFE_PATH_ID_PATTERN)]


class MessageDict(TypedDict):
    """One chat turn as {role, content} for LLM history payloads."""

    role: Annotated[str, StringConstraints(max_length=MAX_MESSAGE_LENGTH)]
    content: Annotated[str, StringConstraints(max_length=MAX_MESSAGE_LENGTH)]


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
    # Where the file landed in the session workspace, or None when the JuiceFS
    # mirror was unavailable at upload. Server-owned like `description` — the
    # difference between an agent-readable path and one that doesn't exist.
    sandbox_path: str | None = None


class SelectedWorkflowData(BaseModel):
    """Workflow the user attached to a message for execution."""

    id: str
    title: str
    description: str
    prompt: str | None = None
    steps: list[WorkflowStep]


class SelectedCalendarEventData(BaseModel):
    """Calendar event the user attached to a message."""

    id: str
    summary: str
    description: str
    start: GoogleCalendarEventDateTime
    end: GoogleCalendarEventDateTime
    calendarId: str | None = None
    calendarTitle: str | None = None
    backgroundColor: str | None = None
    isAllDay: bool | None = False


class ReplyToMessageData(BaseModel):
    """Data for the message being replied to."""

    id: str
    content: str
    role: Literal["user", "assistant"]


class MessageRequestWithHistory(BaseModel):
    """Chat-stream request carrying the full message history and attachments."""

    message: str = Field(max_length=MAX_MESSAGE_LENGTH)
    conversation_id: SafePathId | None = None
    messages: list[MessageDict]
    fileIds: list[str] | None = []
    fileData: list[FileData] | None = []
    selectedTool: str | None = None
    toolCategory: str | None = None
    selectedWorkflow: SelectedWorkflowData | None = None
    selectedCalendarEvent: SelectedCalendarEventData | None = None
    replyToMessage: ReplyToMessageData | None = None
    # Client-generated id for this SEND, stable across retries: doubles as the
    # idempotency key (duplicate POST -> 409) and the USER MESSAGE ID itself, so
    # the optimistic and persisted records share one key. Path-safe (pin route).
    turn_id: SafePathId | None = None
    is_onboarding_demo: bool = False
    # Voice sessions set this so the stream holds open until a delegated executor
    # delivers its narrated answer (a `voice_tts` SSE frame). Text clients leave
    # it False — their executor result arrives out-of-band over the WebSocket.
    voice_mode: bool = False
    # DEV-ONLY (ENV=development): per-request model overrides from the chat-header
    # selector. `use_default_models` keeps the plan-routed default; otherwise these
    # ids (keys of DEV_MODEL_OPTIONS) pin the comms / executor models. Ignored in prod.
    comms_model: str | None = None
    executor_model: str | None = None
    use_default_models: bool = True
    # Platform-native id of the user's message (WhatsApp wamid, Telegram
    # message_id, Discord id, Slack ts). Set only by bot turns for later native
    # reactions; web and other clients leave it None.
    platform_message_id: str | None = None


class MessageRequest(BaseModel):
    """Minimal chat request with a single message."""

    message: str = Field(max_length=MAX_MESSAGE_LENGTH)
