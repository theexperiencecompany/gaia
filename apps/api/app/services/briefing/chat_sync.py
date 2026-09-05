"""Brief <-> bot-chat sync.

Platform delivery of the brief is fire-and-forget (RabbitMQ -> bot), so the
bot's conversation history never contains the brief, and the user's replies to
it never reach the next run. This module closes the loop in both directions:
``persist_delivered_brief`` writes the delivered bubbles into each platform's
bot conversation as an assistant turn (so "yeah send them" lands with real
context), and ``format_replies_block`` reads the user's bot-chat messages back
into the next briefing/night-shift context.

Web/mobile conversations are deliberately excluded from the reply read: bot
chats are short reactions to GAIA's outbound, while UI chats are long working
sessions that would drown the briefing context.
"""

from datetime import UTC, datetime
from typing import cast

from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    MessageModel,
    UpdateMessagesRequest,
)
from app.models.user_models import AuthenticatedUser
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.platform_link_service import PlatformLinkService
from shared.py.wide_events import log

# The reply block is bounded by design: the newest handful of short reactions is
# what tomorrow's run needs, not a transcript.
MAX_REPLY_LINES = 10
MAX_REPLY_CHARS = 200


async def persist_bot_message(user_id: str, user: dict, platform: str, parts: list[str]) -> None:
    """Append one assistant turn (``parts``, joined) to a platform's bot conversation.

    The bot never sees GAIA's outbound in its own history (platform delivery is
    fire-and-forget), so this writes it in so the user's next reply lands with
    context. Best-effort: the message is already delivered, so a history-sync
    failure must not fail (and re-send) the caller's flow — log it.
    """
    if not parts:
        return
    linked = await PlatformLinkService.get_linked_platforms(user_id)
    entry = linked.get(platform)
    if not entry:
        return
    platform_user_id = entry["platformUserId"]
    date_iso = datetime.now(UTC).isoformat()
    try:
        # Resolve through bot_sessions (never cache): /new re-mints the id.
        conversation_id = await BotService.get_or_create_session(
            platform, str(platform_user_id), None, cast(AuthenticatedUser, user)
        )
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[MessageModel(type="bot", response="\n\n".join(parts), date=date_iso)],
            ),
            {"user_id": user_id},
        )
    except Exception as e:
        log.warning("briefing.chat_sync_failed", user_id=user_id, platform=platform, error=str(e))


async def persist_delivered_brief(
    user_id: str, user: dict, parts: list[str], channels: list[str]
) -> None:
    """Append the delivered brief to each bot platform's conversation history."""
    platforms = [c for c in channels if ConversationSource.coerce(c) in BOT_CONVERSATION_SOURCES]
    if not platforms or not parts:
        return
    for platform in platforms:
        await persist_bot_message(user_id, user, platform, parts)


async def format_replies_block(user_id: str, since: datetime) -> str:
    """The user's bot-chat messages since ``since``, newest last, bounded."""
    replies = await conversation_repository.list_bot_replies_since(
        user_id, since, limit=MAX_REPLY_LINES
    )
    if not replies:
        return "No replies since the last brief."
    lines: list[str] = []
    for reply in reversed(replies):  # newest last, reading order
        text = " ".join((reply.text or "").split())
        if len(text) > MAX_REPLY_CHARS:
            text = text[:MAX_REPLY_CHARS] + "..."
        lines.append(f"- [{reply.source}] {text}")
    return "\n".join(lines)
