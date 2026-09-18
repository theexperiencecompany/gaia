"""Short single-use codes for the local session-import CLI.

Mirrors live_code, a Redis-backed code with a TTL, but authorises a write,
not a view, so it is consumed on redemption: the first resolve deletes it,
so a leaked code cannot be replayed to overwrite a user's logins twice.
"""

from __future__ import annotations

import secrets

from app.constants.browser import (
    BROWSER_IMPORT_TOKEN_ENTROPY_BYTES,
    BROWSER_IMPORT_TOKEN_KEY_PREFIX,
    BROWSER_IMPORT_TOKEN_TTL_SECONDS,
)
from app.db.redis import redis_cache
from app.schemas.browser import ImportTokenRecord


def _key(token: str) -> str:
    return f"{BROWSER_IMPORT_TOKEN_KEY_PREFIX}{token}"


async def mint_import_token(user_id: str) -> str:
    """Return a single-use code that authorises user_id to upload a browser profile."""
    # The entropy constant is 32, which is exactly secrets' own default, so every
    # mutant of this argument (None, or dropping it) mints the same 32-byte token.
    token = secrets.token_urlsafe(BROWSER_IMPORT_TOKEN_ENTROPY_BYTES)  # pragma: no mutate
    await redis_cache.set(
        _key(token),
        ImportTokenRecord(user_id=user_id),
        ttl=BROWSER_IMPORT_TOKEN_TTL_SECONDS,
        model=ImportTokenRecord,
    )
    return token


async def consume_import_token(token: str) -> str | None:
    """Return the user a code authorises, or None if unknown, expired, or already used.

    Single-use: one GETDEL reads and removes the code, so two concurrent
    redemptions cannot both succeed.
    """
    record: ImportTokenRecord | None = await redis_cache.get_and_delete(
        _key(token), model=ImportTokenRecord
    )
    return None if record is None else record.user_id
