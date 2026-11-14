"""The wire shapes of the conversation runtime's surfaces: a send, its acknowledgement, one event."""

from pydantic import BaseModel, Field, model_validator

from app.constants.chat import ConversationSource
from app.models.bot_models import BotDelivery, BotSessionDocument, PartialReply
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


class RetryMessageRequest(BaseModel):
    """Answer the user message target again in place; message_id is minted by the client and makes a resend a no-op."""

    message_id: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)


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
    """A bot session's conversation to follow: its events after after_seq, the bot's delivered-through cursor.

    partial_reply names the reply just past it that the bot had sent only its first bubbles of, so a
    restarted follower sends the rest and repeats none.
    """

    conversation_id: str
    platform_user_id: str
    channel_id: str | None
    is_dm: bool
    after_seq: int = Field(ge=0)
    partial_reply: PartialReply | None = None

    @classmethod
    def of(cls, session: BotSessionDocument, delivery: BotDelivery) -> "ActiveBotConversation":
        """Return the follow of session's conversation from delivery."""
        return cls(
            conversation_id=session.conversation_id,
            platform_user_id=session.platform_user_id,
            channel_id=session.channel_id,
            is_dm=session.channel_id is None,
            after_seq=delivery.delivered_seq,
            partial_reply=delivery.partial_reply,
        )


class BotDeliveryReport(BaseModel):
    """What a bot follower put on the platform: every item through delivered_seq, plus partial_reply."""

    platform: ConversationSource
    delivered_seq: int = Field(ge=0)
    partial_reply: PartialReply | None = None


class BotDeliveryRecorded(ResponseModel):
    """Whether the report moved the cursor; False for one behind what is already recorded."""

    recorded: bool


class ConversationEvent(ResponseModel):
    """One frame on a conversation's events stream: the screen, a patch to it, or a live delta."""

    frame: ScreenStreamFrame
