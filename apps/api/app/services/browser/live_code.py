"""Short capability codes for the bot's live-view link.

The code itself is the secret: anyone holding it can watch and drive the
session, so one is minted per handoff, lives only as long as that handoff may
wait, and is revoked the moment the handoff is settled.
"""

from __future__ import annotations

import secrets

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_LIVE_CODE_HANDOFF_PREFIX,
    BROWSER_LIVE_CODE_KEY_PREFIX,
)
from app.db.redis import redis_cache
from app.schemas.browser import LiveCodeRecord


def _key(code: str) -> str:
    return f"{BROWSER_LIVE_CODE_KEY_PREFIX}{code}"


def _handoff_key(handoff_id: str) -> str:
    return f"{BROWSER_LIVE_CODE_HANDOFF_PREFIX}{handoff_id}"


async def mint_live_code(session_id: str, user_id: str, handoff_id: str) -> str:
    """Create a short code that opens the session for its owner while this handoff waits."""
    code = secrets.token_urlsafe(BROWSER_LIVE_CODE_ENTROPY_BYTES)
    ttl: int = settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
    await redis_cache.set(
        _key(code),
        LiveCodeRecord(session_id=session_id, user_id=user_id, handoff_id=handoff_id),
        ttl=ttl,
        model=LiveCodeRecord,
    )
    await redis_cache.client.set(_handoff_key(handoff_id), code, ex=ttl)
    return code


async def revoke_handoff_live_code(handoff_id: str) -> None:
    """Close the link minted for this handoff, if one was: it is settled, so nobody is to act in that browser now."""
    code = await redis_cache.client.getdel(_handoff_key(handoff_id))
    if code is not None:
        await redis_cache.delete(_key(code))


async def resolve_live_code(code: str) -> LiveCodeRecord | None:
    """Return the session and owner a code opens, or None if unknown, expired or revoked."""
    return await redis_cache.get(_key(code), model=LiveCodeRecord)


async def live_code_remaining_seconds(code: str) -> float:
    """Seconds the code stays valid; 0 once it has lapsed, so a socket bound to it closes at once."""
    remaining = await redis_cache.ttl_seconds(_key(code))
    return float(remaining) if remaining is not None else 0.0
