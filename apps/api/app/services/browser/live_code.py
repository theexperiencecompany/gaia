"""Short capability codes for the bot's live-view link.

A code maps to a live-view session and its owner in Redis, so the delivered link
is ``browser.heygaia.io/{code}`` — no 32-char session id and no long ``?t=`` token
in the URL. The code itself is the secret: anyone holding it can watch and drive the
session until the TTL lapses, exactly like the takeover token it replaces.
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
    """Create a short code that resolves to ``(session_id, user_id)`` for the TTL window."""
    code = secrets.token_urlsafe(BROWSER_LIVE_CODE_ENTROPY_BYTES)
    await redis_cache.set(
        _key(code),
        LiveCodeRecord(session_id=session_id, user_id=user_id),
        ttl=BROWSER_LIVE_CODE_TTL_SECONDS,
        model=LiveCodeRecord,
    )
    return code


async def resolve_live_code(code: str) -> LiveCodeRecord | None:
    """The session + owner a code opens, or ``None`` if unknown/expired."""
    return await redis_cache.get(_key(code), model=LiveCodeRecord)
