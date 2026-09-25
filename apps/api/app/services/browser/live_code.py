"""Short capability codes for the bot's live-view link.

The code itself is the secret: anyone holding it can watch and drive the
session until the TTL lapses, same as the takeover token it replaces.
"""

from __future__ import annotations

import secrets

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_LIVE_CODE_KEY_PREFIX,
    BROWSER_LIVE_CODE_TTL_SECONDS,
)
from app.db.redis import redis_cache
from app.schemas.browser import LiveCodeRecord


def _key(code: str) -> str:
    return f"{BROWSER_LIVE_CODE_KEY_PREFIX}{code}"


async def mint_live_code(session_id: str, user_id: str) -> str:
    """Create a short code that resolves to the session id and user id for the TTL window."""
    code = secrets.token_urlsafe(BROWSER_LIVE_CODE_ENTROPY_BYTES)
    await redis_cache.set(
        _key(code),
        LiveCodeRecord(session_id=session_id, user_id=user_id),
        ttl=BROWSER_LIVE_CODE_TTL_SECONDS,
        model=LiveCodeRecord,
    )
    return code


async def resolve_live_code(code: str) -> LiveCodeRecord | None:
    """Return the session and owner a code opens, or None if unknown or expired."""
    return await redis_cache.get(_key(code), model=LiveCodeRecord)


async def live_code_remaining_seconds(code: str) -> float:
    """Seconds the code stays valid; 0 once it has lapsed, so a socket bound to it closes at once."""
    remaining = await redis_cache.ttl_seconds(_key(code))
    return float(remaining) if remaining is not None else 0.0
