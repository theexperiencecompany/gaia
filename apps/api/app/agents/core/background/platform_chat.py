"""Post a proactive message into the user's chat with GAIA on a messaging platform.

Anything GAIA sends on its own initiative to Telegram/WhatsApp/Discord/Slack/
iMessage (a workflow result, a fired reminder, a notification) goes through
post_to_platform_chat, so it lands where the user will reply: saved into
their DM conversation and recorded in that conversation's LangGraph thread.
Without both, the user's reply reaches an agent that has no idea what it just
said.

Being the one path, it is also where quiet hours apply: a message the policy
holds (app/services/delivery/quiet_hours.py) is scheduled as a durable job for
the window's end instead of being sent, so no caller knows about quiet hours.
"""

from datetime import UTC, datetime
import hashlib
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.agents.core.background.thread_record import record_platform_delivery
from app.constants.log_tags import LogTag
from app.constants.notifications import (
    DEFERRED_CHAT_MESSAGE_JOB_PREFIX,
    DEFERRED_CHAT_MESSAGE_TASK,
    ProactiveMessageClass,
)
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource, MessageModel, UpdateMessagesRequest
from app.models.user_models import AuthenticatedUser
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.delivery.chat_channel import ChatChannel
from app.services.delivery.quiet_hours import held_until
from app.services.outbound_delivery import OutboundResult, publish_outbound_message
from app.utils.message_breaks import split_message_bubbles
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


class DeferredChatMessage(BaseModel):
    """A proactive message held for quiet hours: everything needed to post it later."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    source: ConversationSource
    platform_user_id: str
    text: str
    origin: str
    message_class: ProactiveMessageClass

    @property
    def channel(self) -> ChatChannel:
        """The platform and account the message was addressed to."""
        return ChatChannel(source=self.source, platform_user_id=self.platform_user_id)


async def post_to_platform_chat(
    *,
    user: AuthenticatedUser,
    channel: ChatChannel,
    text: str,
    origin: str,
    message_class: ProactiveMessageClass,
) -> OutboundResult:
    """Save, send, and remember one proactive message in the user's DM on channel's platform.

    A message the user's quiet hours hold is scheduled for their end (DEFERRED).
    Otherwise it is saved to the DM, published as bubbles, and once published
    recorded in that conversation's checkpoint. Session, storage or scheduling
    failures raise.
    """
    deliver_at = await _quiet_hours_end(user.user_id, message_class)
    if deliver_at is not None:
        await _schedule(
            DeferredChatMessage(
                user_id=user.user_id,
                source=channel.source,
                platform_user_id=channel.platform_user_id,
                text=text,
                origin=origin,
                message_class=message_class,
            ),
            deliver_at,
        )
        return OutboundResult.DEFERRED

    source, platform_user_id = channel.source, channel.platform_user_id
    # Comms splits its reply into bubbles with the break sentinel; the publish
    # and the checkpoint record both need the split, not the raw control tokens.
    bubbles = split_message_bubbles(text)
    conversation_id = await BotService.get_or_create_session(
        platform=source.value,
        platform_user_id=platform_user_id,
        # No channel: this goes to the user's DM, the only destination the
        # platform link can name. See BotService.build_session_key.
        channel_id=None,
        user=user,
        is_dm=True,
    )
    bot_message = MessageModel(type="bot", response=text, date=datetime.now(UTC).isoformat())
    bot_message.message_id = str(uuid4())
    await update_messages(
        UpdateMessagesRequest(conversation_id=conversation_id, messages=[bot_message]),
        user=user,
    )
    # The channel already carries the account id; destination_override skips a
    # second read of the user document to recompute it.
    result = await publish_outbound_message(
        source, user.user_id, bubbles, destination_override=platform_user_id
    )
    outcome: dict[str, object] = {
        "platform": source.value,
        "conversation_id": conversation_id,
        "message_id": bot_message.message_id,
        "bubbles": len(bubbles),
    }
    if result is OutboundResult.FAILED:
        log.error(f"{LogTag.AGENT} proactive platform publish failed", **outcome)
    else:
        log.info(
            f"{LogTag.AGENT} proactive message posted to platform chat",
            result=result.value,
            **outcome,
        )
    if result is OutboundResult.PUBLISHED:
        delivered_text = "\n\n".join(b.strip() for b in bubbles if b.strip())
        await record_platform_delivery(
            conversation_id,
            f"[Delivered to the user on {source.display_name} ({origin})]: {delivered_text}",
        )
    return result


async def _quiet_hours_end(user_id: str, message_class: ProactiveMessageClass) -> datetime | None:
    """Return when the user's quiet hours release a message of message_class, or None for now.

    Read from the stored user, not the caller's context: a run's context can be
    a partial user whose window is the default rather than the one they set.
    """
    user_doc = await user_repository.get(user_id)
    if user_doc is None:
        raise LookupError(f"proactive message for unknown user {user_id}")
    # astimezone reads a naive now() as the same instant, so dropping UTC is equivalent.
    now = datetime.now(UTC)  # pragma: no mutate
    return held_until(message_class, user_doc.quiet_hours, user_doc.timezone, now)


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
        message_class=message.message_class.value,
        deliver_at=deliver_at.isoformat(),
    )
