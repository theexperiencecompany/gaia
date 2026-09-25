"""Redis-backed ownership registry for live browser sessions.

Map a host session_id to the user who owns it (for live-view authorization)
and to the host's live-view WebSocket URL (so the proxy needs no round-trip).
Written by session.py on create, cleared on delete; the TTL is only a safety
net for a leaked entry.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import log

_KEY_PREFIX = "browser:sess:"
# Only bounds a leaked entry; must stay well above the longest possible run
# (task timeout 600s + 5 handoffs x 600s = 3600s) so a mid-run handoff is never
# locked out of its own live view by an expiring ownership entry.
_REGISTRY_TTL_SECONDS = 7200


class SessionRegistryEntry(BaseModel):
    """Who owns a browser session and where the host streams its live view."""

    owner: str
    live_ws: str | None = None


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


async def register_session(session_id: str, user_id: str, live_ws: str | None = None) -> bool:
    """Record that user_id owns session_id and where its live view lives.

    Return True only when the ownership write succeeded; on False the
    live-view link must not be handed out, since it can never authorize.
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
    """Return the full registry entry (owner plus live-view WS URL), or None if unknown."""
    return await redis_cache.get(_key(session_id), model=SessionRegistryEntry)


async def session_owner(session_id: str) -> str | None:
    """Return the user id that owns session_id, or None if it is not registered."""
    entry = await get_session_entry(session_id)
    return entry.owner if entry else None


async def unregister_session(session_id: str) -> None:
    """Forget a session once it is disposed."""
    log.set(browser={"session_id": session_id, "operation": "registry_unregister"})
    await redis_cache.delete(_key(session_id))
