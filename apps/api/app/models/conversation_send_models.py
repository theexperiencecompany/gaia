"""The wire shapes of the conversation runtime's surfaces: a send, its acknowledgement, one event."""

from pydantic import BaseModel, Field, model_validator

from app.models.conversation_frame_models import OutputFrame
from app.models.message_models import (
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.schemas.common import ResponseModel
from shared.py.analytics.catalog.properties import Identifier


class SendMessageRequest(BaseModel):
    """A user message sent into a conversation; message_id is minted by the client and makes a resend a no-op."""

    message_id: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=32768)
    reply_to: str | None = None
    retry_of: str | None = None
    file_ids: list[str] = Field(default_factory=list)
    voice: bool = False
    selected_tool: Identifier | None = None
    tool_category: Identifier | None = None
    selected_workflow: SelectedWorkflowData | None = None
    selected_calendar_event: SelectedCalendarEventData | None = None
    # The replied-to message's content, which the turn quotes; reply_to is its id.
    reply_to_message: ReplyToMessageData | None = None

    @model_validator(mode="after")
    def _one_reply_target(self) -> "SendMessageRequest":
        if self.reply_to_message is not None and self.reply_to not in (
            None,
            self.reply_to_message.id,
        ):
            raise ValueError("reply_to and reply_to_message.id name different messages")
        return self


class MessageAccepted(ResponseModel):
    """The message is durable at seq; its reply arrives on the conversation's events stream."""

    conversation_id: str
    message_id: str
    seq: int


class BotMessageAccepted(MessageAccepted):
    """A bot message accepted, with the token the bot follows the events stream with."""

    session_token: str


class ConversationEvent(ResponseModel):
    """One frame on a conversation's events stream; stream_id is the cursor to resume after, None for a log replay."""

    stream_id: str | None
    frame: OutputFrame
