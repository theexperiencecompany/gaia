"""Where the user actually is: the last time they SENT a message on each surface, and whether a call is live.

Only the user's own inbound turns write the stamps. GAIA's outbound deliveries bump
bot_sessions.updated_at and the conversation's updatedAt too, which is why
neither can tell where the user is. A call is not a turn: the voice worker holds it
live with a heartbeat, and its end stamps the voice surface.
"""

from collections.abc import Mapping

from app.constants.cache import USER_CALL_PRESENCE_PREFIX, USER_PRESENCE_PREFIX
from app.constants.notifications import (
    CALL_PRESENCE_TTL_SECONDS,
    PRESENCE_ACTIVE_WINDOW_SECONDS,
    PRESENCE_RETENTION_SECONDS,
)
from app.db.redis import redis_cache
from app.models.chat_models import ConversationSource, SourceCategory
from app.models.presence_models import PresenceSnapshot
from app.utils import clock


def _presence_key(user_id: str) -> str:
    return f"{USER_PRESENCE_PREFIX}:{user_id}"


def _call_key(user_id: str) -> str:
    return f"{USER_CALL_PRESENCE_PREFIX}:{user_id}"


def _now_epoch() -> int:
    return int(clock.now().timestamp())


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


async def mark_call_live(user_id: str, room_name: str) -> None:
    """Say the user is in the call in room_name for the next heartbeat window; each beat renews it."""
    await redis_cache.client.set(_call_key(user_id), room_name, ex=CALL_PRESENCE_TTL_SECONDS)


async def read_call_room(user_id: str) -> str | None:
    """Return the LiveKit room of the user's live call, or None when they are not in one."""
    return await redis_cache.client.get(_call_key(user_id))


async def end_call(user_id: str, room_name: str) -> bool:
    """Record the call in room_name as over and stamp the user's last presence on voice.

    False, and nothing changed, when the user is in another call by now: a late end of the
    old room must not end the new one.
    """
    if await read_call_room(user_id) != room_name:
        return False
    await redis_cache.client.delete(_call_key(user_id))
    await record_turn_presence(user_id, ConversationSource.VOICE)
    return True


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
