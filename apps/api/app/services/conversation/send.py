"""A user message entering a conversation on the step: open the conversation, append the message, return at once.

The reply is the step's, started by the append's kick; the instant reaction is the append's
StartAck effect, decided in the background. Neither delays the accept.
"""

from dataclasses import dataclass
from uuid import uuid4

from app.constants.chat import ConversationSource
from app.db.repositories.conversations import conversation_repository
from app.decorators import enforce_cost_budget
from app.models.bot_models import BotChatRequest
from app.models.chat_models import ConversationModel
from app.models.conversation_log_models import BargeIn, UserMessage
from app.models.conversation_send_models import (
    BargeInAccepted,
    BargeInRequest,
    BotMessageAccepted,
    MessageAccepted,
    SendMessageRequest,
)
from app.models.message_models import FileData
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.bot_service import BotService, charge_bot_turn
from app.services.bot_token_service import create_bot_session_token
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.title import title_conversation
from app.services.conversation_service import create_conversation_service
from app.services.files import FileService
from app.utils.background_tasks import spawn_background_task
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import ChatMessageSubmitted
from shared.py.wide_events import log

_TITLE_TASK_NAME = "conversation-title"


@dataclass(frozen=True)
class Sent:
    """An accepted send, the message it logged, and whether it was a resend of one already accepted."""

    accepted: MessageAccepted
    message: UserMessage
    duplicate: bool


async def open_conversation(
    conversation_id: str, user: AuthenticatedUser, source: ConversationSource
) -> bool:
    """Create the conversation when it is new; True when it was created here.

    An existing conversation continues on the step as it is: its thread already holds its history.
    """
    if await conversation_repository.exists(conversation_id, user_id=user.user_id):
        return False
    await create_conversation_service(
        ConversationModel(conversation_id=conversation_id, source=source), user
    )
    return True


async def send_message(
    conversation_id: str,
    user: AuthenticatedUser,
    body: SendMessageRequest,
    surface: ConversationSource,
    *,
    platform_message_id: str | None = None,
) -> Sent:
    """Append the user's message to the conversation and return its seq; a resend returns the first seq."""
    files: list[FileData] = []
    if body.file_ids:
        await FileService.attach_uploads(body.file_ids, user.user_id, conversation_id)
        files = await FileService.get_uploads(body.file_ids, user.user_id, conversation_id)
    reply_to_message = body.reply_to_message
    message = UserMessage(
        id=body.message_id,
        text=body.text,
        surface=surface,
        platform_message_id=platform_message_id,
        reply_to=body.reply_to or (reply_to_message.id if reply_to_message else None),
        retry_of=body.retry_of,
        file_ids=tuple(body.file_ids),
        files=tuple(files),
        voice=body.voice,
        selected_tool=body.selected_tool,
        tool_category=body.tool_category,
        selected_workflow=body.selected_workflow,
        selected_calendar_event=body.selected_calendar_event,
        reply_to_message=reply_to_message,
    )
    accepted = await accept(runtime_ports(), conversation_id, user.user_id, message)
    seq = accepted.appended.logged.seq
    if accepted.kick_failed:
        # The message is durable and unsettled, so the sweeper starts its step.
        log.error(
            "conversation step kick failed after accept; the sweeper will advance it",
            conversation_id=conversation_id,
            seq=seq,
        )
    duplicate = accepted.appended.duplicate
    log.set_ns("conversation", seq=seq, duplicate=duplicate)
    return Sent(
        accepted=MessageAccepted(conversation_id=conversation_id, message_id=message.id, seq=seq),
        message=message,
        duplicate=duplicate,
    )


async def submit_message(
    conversation_id: str,
    user: AuthenticatedUser,
    body: SendMessageRequest,
    surface: ConversationSource,
) -> MessageAccepted:
    """Charge the day's budget, open the conversation on the step, accept the message and count it."""
    await enforce_cost_budget(user.user_id, feature_key="chat_messages")
    created = await open_conversation(conversation_id, user, surface)
    sent = await send_message(conversation_id, user, body, surface)
    if sent.duplicate:
        return sent.accepted
    if created:
        spawn_background_task(
            title_conversation(conversation_id, user, sent.message), name=_TITLE_TASK_NAME
        )
    capture(
        UserId(user.user_id),
        ChatMessageSubmitted(
            source=surface.value,
            has_files=bool(body.file_ids),
            stream_id=sent.accepted.message_id,
            is_retry=body.retry_of is not None,
            is_new_conversation=created,
            file_count=len(body.file_ids),
            is_reply=body.reply_to is not None,
        ),
    )
    return sent.accepted


async def submit_bot_message(body: BotChatRequest, user: AuthenticatedUser) -> BotMessageAccepted:
    """Accept a bot user's message into their session's conversation, which keeps its history."""
    platform, user_id = body.platform, user.user_id
    conversation_id = await BotService.get_or_create_session(
        platform, body.platform_user_id, body.channel_id, user, is_dm=body.is_dm
    )
    message_id = (
        f"{platform}:{body.platform_message_id}" if body.platform_message_id else uuid4().hex
    )
    await charge_bot_turn(user_id, body, message_id)
    sent = await send_message(
        conversation_id,
        user,
        SendMessageRequest(message_id=message_id, text=body.message, file_ids=body.file_ids or []),
        ConversationSource(platform),
        platform_message_id=body.platform_message_id,
    )
    token = create_bot_session_token(
        user_id=user_id, platform=platform, platform_user_id=body.platform_user_id
    )
    return BotMessageAccepted(**sent.accepted.model_dump(), session_token=token)


async def submit_barge_in(
    conversation_id: str, user: AuthenticatedUser, body: BargeInRequest
) -> BargeInAccepted:
    """Log that the user spoke over a voice reply; the step cuts the reply to what they heard."""
    barge = BargeIn(
        id=f"{body.reply_id}:barge", reply_id=body.reply_id, heard_through=body.heard_through
    )
    accepted = await accept(runtime_ports(), conversation_id, user.user_id, barge)
    seq = accepted.appended.logged.seq
    log.set_ns("conversation", seq=seq, duplicate=accepted.appended.duplicate)
    return BargeInAccepted(conversation_id=conversation_id, seq=seq)
