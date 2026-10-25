"""Which chat surface the user is actually on: the last time they SENT a message there.

Only the user's own inbound turns write it. GAIA's outbound deliveries bump
bot_sessions.updated_at and the conversation's updatedAt too, which is why
neither can tell where the user is.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from app.constants.cache import USER_PRESENCE_PREFIX
from app.constants.notifications import (
    PRESENCE_ACTIVE_WINDOW_SECONDS,
    PRESENCE_RETENTION_SECONDS,
)
from app.db.redis import redis_cache
from app.models.chat_models import ConversationSource, SourceCategory
from app.models.presence_models import PresenceSnapshot


def _presence_key(user_id: str) -> str:
    return f"{USER_PRESENCE_PREFIX}:{user_id}"


def _now_epoch() -> int:
    return int(datetime.now(UTC).timestamp())


def _parse(stored: Mapping[str, str], captured_at: int) -> PresenceSnapshot:
    """Keep only known surfaces with a whole-second stamp; anything else in the hash is dropped."""
    last_seen = {
        field: int(stamp)
        for field, stamp in stored.items()
        if ConversationSource.coerce(field) is not None and stamp.isdecimal()
    }
    return {"captured_at": captured_at, "last_seen": last_seen}


async def record_turn_presence(user_id: str, source: ConversationSource) -> PresenceSnapshot:
    """Stamp now as the user's last message on source, returning their presence from before this turn."""
    key = _presence_key(user_id)
    now = _now_epoch()
    async with redis_cache.client.pipeline(transaction=True) as pipe:
        pipe.hgetall(key)
        pipe.hset(key, mapping={source.value: str(now)})
        pipe.expire(key, PRESENCE_RETENTION_SECONDS)
        before, _, _ = await pipe.execute()
    return _parse(before, now)


async def read_presence(user_id: str) -> PresenceSnapshot:
    """Return the user's presence as it stands now."""
    return _parse(await redis_cache.client.hgetall(_presence_key(user_id)), _now_epoch())


def surfaces_by_recency(snapshot: PresenceSnapshot) -> list[tuple[ConversationSource, int]]:
    """Return each known surface with its last-seen epoch, newest first."""
    seen = [
        (source, at)
        for field, at in snapshot["last_seen"].items()
        if (source := ConversationSource.coerce(field)) is not None
    ]
    return sorted(seen, key=lambda entry: entry[1], reverse=True)


def previous_surface(
    snapshot: PresenceSnapshot, current: ConversationSource
) -> ConversationSource | None:
    """Return the surface the user last wrote on before this turn, when it is not current."""
    ranked = surfaces_by_recency(snapshot)
    if not ranked or ranked[0][0] is current:
        return None
    return ranked[0][0]


def active_surface(snapshot: PresenceSnapshot, now_epoch: int) -> ConversationSource | None:
    """Return the surface, app or chat app, the user last wrote on, when inside the active window."""
    newest = next(
        (
            (source, at)
            for source, at in surfaces_by_recency(snapshot)
            if SourceCategory.from_source(source) is not SourceCategory.BG
        ),
        None,
    )
    if newest is None or now_epoch - newest[1] > PRESENCE_ACTIVE_WINDOW_SECONDS:
        return None
    return newest[0]
