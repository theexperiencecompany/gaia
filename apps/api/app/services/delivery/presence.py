"""Which chat surface the user is actually on: the last time they SENT a message there.

Only the user's own inbound turns write it. GAIA's outbound deliveries bump
bot_sessions.updated_at and the conversation's updatedAt too, which is why
neither can tell where the user is.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from app.constants.cache import USER_PRESENCE_PREFIX
from app.constants.notifications import PRESENCE_ACTIVE_WINDOW_SECONDS
from app.db.redis import redis_cache
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource


def _presence_key(user_id: str) -> str:
    return f"{USER_PRESENCE_PREFIX}:{user_id}"


async def record_inbound_activity(user_id: str, source: ConversationSource) -> None:
    """Stamp now as the user's last message on source; the key outlives it by one window."""
    key = _presence_key(user_id)
    client = redis_cache.client
    await client.hset(key, mapping={source.value: str(int(datetime.now(UTC).timestamp()))})
    await client.expire(key, PRESENCE_ACTIVE_WINDOW_SECONDS)


def pick_recent_bot_platform(
    entries: Mapping[str, str], now_epoch: int, window: int
) -> ConversationSource | None:
    """Return the bot platform with the newest stamp inside window; non-bot fields are ignored."""
    newest: tuple[int, ConversationSource] | None = None
    for field, stamp in entries.items():
        source = ConversationSource.coerce(field)
        if source is None or source not in BOT_CONVERSATION_SOURCES:
            continue
        at = int(stamp)
        if now_epoch - at > window:
            continue
        if newest is None or at > newest[0]:
            newest = (at, source)
    return newest[1] if newest else None


async def most_recent_bot_platform(
    user_id: str, now: datetime | None = None
) -> ConversationSource | None:
    """Return the bot platform the user last wrote on within the active window, if any."""
    entries = await redis_cache.client.hgetall(_presence_key(user_id))
    moment = now or datetime.now(UTC)
    return pick_recent_bot_platform(
        entries, int(moment.timestamp()), PRESENCE_ACTIVE_WINDOW_SECONDS
    )
