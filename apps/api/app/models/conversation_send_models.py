"""The wire shapes of the conversation runtime's surfaces: a send, its acknowledgement, one event."""

from pydantic import BaseModel, Field, model_validator

from app.models.conversation_screen_models import ScreenStreamFrame
from app.models.message_models import SelectedCalendarEventData, SelectedWorkflowData
from app.schemas.common import ResponseModel
from shared.py.analytics.catalog.properties import Identifier
from shared.py.conversation_wire import ReplyToMessageData


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


class BargeInRequest(BaseModel):
    """The user spoke over a voice reply, having heard its text up to heard_through characters."""

    reply_id: str = Field(min_length=1, max_length=128)
    heard_through: int = Field(ge=0)


class BargeInAccepted(ResponseModel):
    """The barge-in is durable at seq; a resend for the same reply returns the first seq."""

    conversation_id: str
    seq: int


class MessageAccepted(ResponseModel):
    """The message is durable at seq; its reply arrives on the conversation's events stream."""

    conversation_id: str
    message_id: str
    seq: int


class BotMessageAccepted(MessageAccepted):
    """A bot message accepted, with the token the bot follows the events stream with."""

    session_token: str


class ActiveBotConversation(ResponseModel):
    """A bot session's conversation still answering; a restarted bot follows its events after after_seq.

    The log does not record what a platform delivered: after_seq is the newest settled reply's
    seq, so the follower replays the reply in flight and everything after it.
    """

    conversation_id: str
    platform_user_id: str
    channel_id: str | None
    is_dm: bool
    after_seq: int = Field(ge=0)


class ConversationEvent(ResponseModel):
    """One frame on a conversation's events stream: the screen, a patch to it, or a live delta."""

    frame: ScreenStreamFrame
