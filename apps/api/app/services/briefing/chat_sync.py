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

from app.db.mongodb.collections import conversations_collection
from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    MessageModel,
    UpdateMessagesRequest,
)
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.platform_link_service import PlatformLinkService
from shared.py.wide_events import log

# The reply block is bounded by design: the newest handful of short reactions is
# what tomorrow's run needs, not a transcript.
MAX_REPLY_LINES = 10
MAX_REPLY_CHARS = 200


async def persist_delivered_brief(
    user_id: str, user: dict, parts: list[str], channels: list[str]
) -> None:
    """Append the delivered brief to each bot platform's conversation history.

    Best-effort by design: the brief is already persisted and delivered, so a
    history-sync failure must not fail (and re-send) the whole run — log it.
    """
    platforms = [c for c in channels if ConversationSource.coerce(c) in BOT_CONVERSATION_SOURCES]
    if not platforms or not parts:
        return
    linked = await PlatformLinkService.get_linked_platforms(user_id)
    date_iso = datetime.now(UTC).isoformat()
    for platform in platforms:
        platform_user_id = (linked.get(platform) or {}).get("platformUserId")
        if not platform_user_id:
            continue
        try:
            # Resolve through bot_sessions (never cache): /new re-mints the id.
            conversation_id = await BotService.get_or_create_session(
                platform, str(platform_user_id), None, user
            )
            await update_messages(
                UpdateMessagesRequest(
                    conversation_id=conversation_id,
                    messages=[MessageModel(type="bot", response="\n\n".join(parts), date=date_iso)],
                ),
                {"user_id": user_id},
            )
        except Exception as e:
            log.warning(
                "briefing.chat_sync_failed", user_id=user_id, platform=platform, error=str(e)
            )


async def format_replies_block(user_id: str, since: datetime) -> str:
    """The user's bot-chat messages since ``since``, newest last, bounded.

    Message dates are stored as UTC ISO strings, so ``$gt`` is a string
    comparison — chronologically correct because persistence always writes
    UTC ``isoformat()``.
    """
    since_iso = since.astimezone(UTC).isoformat()
    pipeline = [
        {
            "$match": {
                "user_id": user_id,
                "source": {"$in": [s.value for s in BOT_CONVERSATION_SOURCES]},
            }
        },
        {"$unwind": "$messages"},
        {"$match": {"messages.type": "user", "messages.date": {"$gt": since_iso}}},
        {"$sort": {"messages.date": -1}},
        {"$limit": MAX_REPLY_LINES},
        {"$project": {"_id": 0, "source": 1, "text": "$messages.response"}},
    ]
    docs = await conversations_collection.aggregate(pipeline).to_list(length=MAX_REPLY_LINES)
    if not docs:
        return "No replies since the last brief."
    lines: list[str] = []
    for doc in reversed(docs):  # newest last, reading order
        text = " ".join(str(doc.get("text") or "").split())
        if len(text) > MAX_REPLY_CHARS:
            text = text[:MAX_REPLY_CHARS] + "..."
        lines.append(f"- [{doc.get('source')}] {text}")
    return "\n".join(lines)
