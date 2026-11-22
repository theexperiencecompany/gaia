"""Post a proactive message into the user's chat with GAIA on a messaging platform.

Anything GAIA sends on its own initiative to Telegram/WhatsApp/Discord/Slack/
iMessage (a workflow result, a fired reminder, a notification, the morning
brief with its edition image) goes through post_to_platform_chat, so it lands
where the user will reply: logged as a Notice in their DM conversation, which
the bot's follower sends and the next comms step reads.

Being the one path, it is also where quiet hours apply to a message: one sent
inside the user's quiet hours (quiet_hours.quiet_hours_end), unless its class
is exempt, is scheduled as a durable job for their end instead of being sent,
so no caller knows about quiet hours.
"""

from datetime import datetime
import hashlib

from pydantic import BaseModel, ConfigDict

from app.constants.log_tags import LogTag
from app.constants.notifications import (
    CHAT_CAPTION_MAX_CHARS,
    DEFERRED_CHAT_MESSAGE_JOB_PREFIX,
    DEFERRED_CHAT_MESSAGE_TASK,
    QUIET_HOURS_EXEMPT,
    ProactiveMessageClass,
)
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import Notice
from app.models.user_models import AuthenticatedUser
from app.services.bot_service import BotService
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.delivery.chat_channel import ChatChannel, ChatChannelBasis
from app.services.outbound_delivery import OutboundResult
from app.services.quiet_hours import quiet_hours_end
from app.utils.message_breaks import split_for_caption, split_message_bubbles
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER
from shared.py.wide_events import log


class ProactiveMessage(BaseModel):
    """One message GAIA sends on its own: the Notice it logs, and the quiet-hours class it obeys.

    notice_id keys the Notice, so a retried send logs it once; with image_url the
    follower sends the image captioned with the first bubble.
    """

    model_config = ConfigDict(frozen=True)

    notice_id: str
    text: str
    origin: str
    message_class: ProactiveMessageClass
    image_url: str | None = None


class DeferredChatMessage(BaseModel):
    """A proactive message held for quiet hours: everything needed to post it later."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    user_id: str
    source: ConversationSource
    platform_user_id: str
    basis: ChatChannelBasis
    message: ProactiveMessage

    @property
    def channel(self) -> ChatChannel:
        """The platform and account the message was addressed to."""
        return ChatChannel(
            source=self.source, platform_user_id=self.platform_user_id, basis=self.basis
        )


def _captioned(bubbles: list[str]) -> list[str]:
    """Split the first bubble so it fits a photo caption; the rest follows the photo as text."""
    first, *later = bubbles
    return [*split_for_caption(first, limit=CHAT_CAPTION_MAX_CHARS), *later]


async def post_to_platform_chat(
    *, user: AuthenticatedUser, channel: ChatChannel, message: ProactiveMessage
) -> OutboundResult:
    """Log message as a Notice in the user's DM on channel's platform.

    A message the user's quiet hours hold is scheduled for their end (DEFERRED);
    one with nothing to say is SKIPPED.
    """
    bubbles = split_message_bubbles(message.text)
    if not bubbles:
        return OutboundResult.SKIPPED
    deliver_at = await _quiet_hours_end(user.user_id, message.message_class)
    if deliver_at is not None:
        await _schedule(
            DeferredChatMessage(
                user_id=user.user_id,
                source=channel.source,
                platform_user_id=channel.platform_user_id,
                basis=channel.basis,
                message=message,
            ),
            deliver_at,
        )
        return OutboundResult.DEFERRED

    conversation_id = await BotService.get_or_create_session(
        platform=channel.source.value,
        platform_user_id=channel.platform_user_id,
        # No channel: this goes to the user's DM, the only destination the
        # platform link can name. See BotService.build_session_key.
        channel_id=None,
        user=user,
        is_dm=True,
    )
    notice = Notice(
        id=message.notice_id,
        text=NEW_MESSAGE_BREAKER.join(_captioned(bubbles) if message.image_url else bubbles),
        origin=message.origin,
        image_url=message.image_url,
    )
    await accept(runtime_ports(), conversation_id, user.user_id, notice)
    log.info(
        f"{LogTag.AGENT} proactive message logged in platform chat",
        platform=channel.source.value,
        conversation_id=conversation_id,
        notice_id=message.notice_id,
        bubbles=len(bubbles),
        image=message.image_url is not None,
    )
    return OutboundResult.PUBLISHED


async def _quiet_hours_end(user_id: str, message_class: ProactiveMessageClass) -> datetime | None:
    """Return when the user's quiet hours release a message of message_class, or None for now."""
    if message_class in QUIET_HOURS_EXEMPT:
        return None
    return await quiet_hours_end(user_id)


async def _schedule(message: DeferredChatMessage, deliver_at: datetime) -> None:
    """Persist message as an ARQ job that posts it at deliver_at.

    The job id hashes the message and its release time, so sending the same
    message twice inside one window schedules it once, while a message held
    again after the user moved their window gets a job of its own.
    """
    digest = hashlib.sha256(
        f"{message.model_dump_json()}|{deliver_at.isoformat()}".encode()
    ).hexdigest()[:32]
    await enqueue_worker_job(
        await RedisPoolManager.get_pool(),
        DEFERRED_CHAT_MESSAGE_TASK,
        message,
        _job_id=f"{DEFERRED_CHAT_MESSAGE_JOB_PREFIX}{digest}",
        _defer_until=deliver_at,
    )
    log.info(
        f"{LogTag.AGENT} proactive message held for quiet hours",
        platform=message.source.value,
        message_class=message.message.message_class.value,
        deliver_at=deliver_at.isoformat(),
    )
