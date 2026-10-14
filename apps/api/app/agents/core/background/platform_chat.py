"""Post a proactive message into the user's chat with GAIA on a messaging platform.

Anything GAIA sends on its own initiative to Telegram/WhatsApp/Discord/Slack/
iMessage (a workflow result, a fired reminder, a notification, the morning
brief with its edition image) goes through post_to_platform_chat, so it lands
where the user will reply: saved into their DM conversation and recorded in
that conversation's LangGraph thread.
Without both, the user's reply reaches an agent that has no idea what it just
said.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.agents.core.background.thread_record import record_platform_delivery
from app.constants.log_tags import LogTag
from app.constants.notifications import CHAT_CAPTION_MAX_CHARS
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.user_models import AuthenticatedUser
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import (
    OutboundResult,
    publish_outbound_message,
    publish_outbound_photo,
)
from app.utils.message_breaks import split_for_caption, split_message_bubbles
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class PlatformImage:
    """A hosted image sent as a photo, the message text as its caption."""

    url: str
    filename: str


async def _publish(
    channel: ChatChannel, user_id: str, bubbles: list[str], image: PlatformImage | None
) -> OutboundResult:
    """Publish the bubbles, or the image captioned with them.

    A caption past the platform limit continues as follow-up text in the same
    chat lane, so it arrives after the photo; nothing follows a failed photo.
    """
    source, platform_user_id = channel.source, channel.platform_user_id
    if image is None:
        return await publish_outbound_message(
            source, user_id, bubbles, destination_override=platform_user_id
        )
    caption, *rest = split_for_caption("\n\n".join(bubbles), limit=CHAT_CAPTION_MAX_CHARS)
    result = await publish_outbound_photo(
        source,
        user_id,
        image.url,
        image.filename,
        caption=caption,
        destination_override=platform_user_id,
    )
    if result is OutboundResult.PUBLISHED and rest:
        return await publish_outbound_message(
            source, user_id, rest, destination_override=platform_user_id
        )
    return result


async def post_to_platform_chat(
    *,
    user: AuthenticatedUser,
    channel: ChatChannel,
    text: str,
    origin: str,
    image: PlatformImage | None = None,
) -> OutboundResult:
    """Save, send, and remember one proactive message in the user's DM on channel's platform.

    Publishes as ordered bubbles (or, with image, as that photo captioned with the text),
    then records it in the conversation checkpoint as "[Delivered to the user on <platform> (<origin>)]".
    A session or storage failure raises; the publish outcome is returned.
    """
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
    result = await _publish(channel, user.user_id, bubbles, image)
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
