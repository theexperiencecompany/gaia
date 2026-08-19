"""Redis-backed ownership registry for live browser sessions.

Maps a host ``session_id`` to the user who owns it (for live-view authorization)
and to the host's live-view WebSocket URL (so the live-view proxy can reach the
host without a round-trip). Written by ``session.py`` on create, cleared on
delete; the TTL is only a safety net for a leaked entry.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import log

_KEY_PREFIX = "browser:sess:"
# Register on create, unregister on delete. This TTL only bounds an entry that
# leaked because delete never ran; it must stay well above the longest possible
# run (task timeout 600s + up to 5 handoffs × 600s = 3600s) so a live session /
# mid-run handoff is never locked out of its own live view by an expiring
# ownership entry. 2h keeps that margin while still bounding a genuine leak.
_REGISTRY_TTL_SECONDS = 7200


class SessionRegistryEntry(BaseModel):
    """Who owns a browser session and where the host streams its live view."""

    owner: str
    live_ws: str | None = None


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


async def register_session(session_id: str, user_id: str, live_ws: str | None = None) -> bool:
    """Record that ``user_id`` owns ``session_id`` and where its live view lives.

    Returns ``True`` only when the ownership write succeeded. Callers must not
    proceed to hand the session's live-view link to a user on ``False`` — without
    the registry entry that link can never authorize.
    """
    log.set(browser={"session_id": session_id, "operation": "registry_register"})
    entry = SessionRegistryEntry(owner=user_id, live_ws=live_ws)
    stored = await redis_cache.set(
        _key(session_id), entry, ttl=_REGISTRY_TTL_SECONDS, model=SessionRegistryEntry
    )
    if not stored:
        log.warning(
            f"{LogTag.BROWSER} browser session registry write failed", session_id=session_id
        )
    return bool(stored)


async def get_session_entry(session_id: str) -> SessionRegistryEntry | None:
    """The full registry entry (owner + live-view WS URL), or ``None`` if unknown."""
    return await redis_cache.get(_key(session_id), model=SessionRegistryEntry)


async def session_owner(session_id: str) -> str | None:
    """The user id that owns ``session_id``, or ``None`` if it is not registered."""
    entry = await get_session_entry(session_id)
    return entry.owner if entry else None


async def unregister_session(session_id: str) -> None:
    """Forget a session once it is disposed."""
    log.set(browser={"session_id": session_id, "operation": "registry_unregister"})
    await redis_cache.delete(_key(session_id))
