from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import TypedDict

from app.constants.chat import MAX_MESSAGE_LENGTH
from app.constants.vfs import SAFE_PATH_ID_PATTERN
from app.models.calendar_models import GoogleCalendarEventDateTime
from app.models.workflow_models import WorkflowStep
from shared.py.analytics.catalog.properties import Identifier

SafePathId = Annotated[str, StringConstraints(pattern=SAFE_PATH_ID_PATTERN)]


class MessageDict(TypedDict):
    """One chat turn as {role, content} for LLM history payloads."""

    # Uncapped: a turn echoes a stored reply no cap governs, so a cap bricks the chat. Readers clip.
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
    # Where the file landed in the session workspace, or None when it is not
    # mirrored. Server-owned and filled from MongoDB on the agent path only;
    # the upload response never carries it.
    sandbox_path: str | None = None


class SelectedWorkflowData(BaseModel):
    """Workflow the user attached to a message for execution."""

    # Workflow ids are generated slugs (wf_<hex>); chat:message_submitted carries this one.
    id: Identifier
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


class MessageRequest(BaseModel):
    """Minimal chat request with a single message."""

    message: str = Field(max_length=MAX_MESSAGE_LENGTH)
