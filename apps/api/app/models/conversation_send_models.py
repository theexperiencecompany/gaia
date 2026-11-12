"""The wire shapes of the conversation runtime's surfaces: a send, its acknowledgement, one event."""

from pydantic import BaseModel, Field

from app.models.conversation_frame_models import OutputFrame
from app.schemas.common import ResponseModel


class SendMessageRequest(BaseModel):
    """A user message sent into a conversation; message_id is minted by the client and makes a resend a no-op."""

    message_id: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=32768)
    reply_to: str | None = None
    retry_of: str | None = None
    file_ids: list[str] = Field(default_factory=list)
    voice: bool = False


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
