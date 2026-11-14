"""The user's bot-chat replies, read back into the next brief.

format_replies_block reads what the user said back in their bot chats into the next
briefing context. Web/mobile conversations are excluded on purpose: UI chats are
long working sessions that would drown the briefing context.
"""

from datetime import datetime

from app.db.repositories.conversations import conversation_repository

# The reply block is bounded by design: the newest handful of short reactions is
# what tomorrow's run needs, not a transcript.
MAX_REPLY_LINES = 10
MAX_REPLY_CHARS = 200


async def format_replies_block(user_id: str, since: datetime) -> str:
    """Render the user's bot-chat messages since the cutoff, newest last, bounded."""
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
