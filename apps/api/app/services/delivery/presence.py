"""Where the user actually is: the last time they SENT a message on each surface, whether a GAIA app is in front of them, and whether a call is live.

Only the user's own inbound turns write the stamps. GAIA's outbound deliveries bump
bot_sessions.updated_at and the conversation's updatedAt too, which is why
neither can tell where the user is. A call is not a turn: the voice worker holds it
live with a heartbeat, and its end stamps the voice surface. An app is looked at while
a client of it beats: visible, focused and in use, and each beat renews that client for one window.
The user's last sign of presence anywhere is one long-lived stamp, written by every signal and read only through read_last_active.
"""

import asyncio
from collections.abc import Mapping

from app.constants.cache import (
    USER_CALL_PRESENCE_PREFIX,
    USER_FOCUS_PRESENCE_PREFIX,
    USER_LAST_SEEN_PREFIX,
    USER_PRESENCE_PREFIX,
)
from app.constants.notifications import (
    CALL_PRESENCE_TTL_SECONDS,
    FOCUS_PRESENCE_TTL_SECONDS,
    POST_CALL_ACTIVE_WINDOW_SECONDS,
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


def _focus_key(user_id: str, surface: ConversationSource) -> str:
    return f"{USER_FOCUS_PRESENCE_PREFIX}:{user_id}:{surface.value}"


def _last_seen_key(user_id: str) -> str:
    return f"{USER_LAST_SEEN_PREFIX}:{user_id}"


#: The apps whose clients report being looked at; a message sent in one says nothing about whether the user is still there.
FOCUS_SURFACES: tuple[ConversationSource, ...] = (
    ConversationSource.WEB,
    ConversationSource.DESKTOP,
)


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
        pipe.set(_last_seen_key(user_id), str(now), ex=PRESENCE_RETENTION_SECONDS)
        before, *_ = await pipe.execute()
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


async def mark_focused(user_id: str, surface: ConversationSource, client_id: str) -> bool:
    """Say the user is looking at the app on surface through client_id for the next heartbeat window; each beat renews it.

    True when no app of theirs was in view before this beat: the user is back.
    """
    now = _now_epoch()
    returned = not await read_focus(user_id)
    key = _focus_key(user_id, surface)
    async with redis_cache.client.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, "-inf", now - FOCUS_PRESENCE_TTL_SECONDS)
        pipe.zadd(key, {client_id: now})
        pipe.expire(key, FOCUS_PRESENCE_TTL_SECONDS)
        pipe.set(_last_seen_key(user_id), str(now), ex=PRESENCE_RETENTION_SECONDS)
        await pipe.execute()
    return returned


async def clear_focus(user_id: str, surface: ConversationSource, client_id: str) -> None:
    """Say the user stopped looking at the app on surface through client_id: it was hidden, or lost focus."""
    await redis_cache.client.zrem(_focus_key(user_id, surface), client_id)


async def read_focus(user_id: str) -> dict[ConversationSource, int]:
    """Return each app the user is looking at now with the epoch of its newest live heartbeat."""
    since = _now_epoch() - FOCUS_PRESENCE_TTL_SECONDS
    async with redis_cache.client.pipeline(transaction=False) as pipe:
        for surface in FOCUS_SURFACES:
            pipe.zrangebyscore(_focus_key(user_id, surface), since, "+inf", withscores=True)
        beats = await pipe.execute()
    return {
        surface: int(max(score for _, score in live))
        for surface, live in zip(FOCUS_SURFACES, beats, strict=True)
        if live
    }


async def read_last_active(user_id: str) -> int | None:
    """Return the epoch of the user's latest sign of presence anywhere, now while they are in a call; None when there is none."""
    last_seen, call_room = await asyncio.gather(
        redis_cache.client.get(_last_seen_key(user_id)), read_call_room(user_id)
    )
    if call_room is not None:
        return _now_epoch()
    return int(last_seen) if last_seen is not None and last_seen.isdecimal() else None


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


def _active_window(source: ConversationSource) -> int:
    """Return how long after its last stamp the user still counts as on source."""
    if source is ConversationSource.VOICE:
        return POST_CALL_ACTIVE_WINDOW_SECONDS
    return PRESENCE_ACTIVE_WINDOW_SECONDS


def active_surface(
    snapshot: PresenceSnapshot, focus: Mapping[ConversationSource, int], now_epoch: int
) -> ConversationSource | None:
    """Return the surface, app or chat app, the user is on now: the newest of what they last wrote and what they look at.

    A chat app counts for PRESENCE_ACTIVE_WINDOW_SECONDS after the user's last message there. A
    web or desktop app counts only while its client beats, whatever was last typed in it, so a
    tab left open in the background is nobody's presence. A call that ended counts only for POST_CALL_ACTIVE_WINDOW_SECONDS.
    """
    wrote = (
        (source, at)
        for source, at in surfaces_by_recency(snapshot)
        if SourceCategory.from_source(source) is not SourceCategory.BG
        and source not in FOCUS_SURFACES
        and now_epoch - at <= _active_window(source)
    )
    newest = max((*wrote, *focus.items()), key=lambda entry: entry[1], default=None)
    return newest[0] if newest is not None else None
