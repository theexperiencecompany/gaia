"""Short single-use codes for the local session-import CLI.

Mirrors ``live_code`` — a Redis-backed code with a TTL — but authorises a write,
not a view, so it is consumed on redemption: the first ``resolve`` deletes it, so
a leaked code cannot be replayed to overwrite a user's logins twice.
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
    """A single-use code that authorises ``user_id`` to upload a browser profile."""
    token = secrets.token_urlsafe(BROWSER_IMPORT_TOKEN_ENTROPY_BYTES)
    await redis_cache.set(
        _key(token),
        ImportTokenRecord(user_id=user_id),
        ttl=BROWSER_IMPORT_TOKEN_TTL_SECONDS,
        model=ImportTokenRecord,
    )
    return token


async def consume_import_token(token: str) -> str | None:
    """The user a code authorises, or ``None`` if unknown/expired/already used.

    Single-use: the code is deleted before the user id is returned, so two
    concurrent redemptions cannot both succeed.
    """
    key = _key(token)
    record = await redis_cache.get(key, model=ImportTokenRecord)
    if record is None:
        return None
    await redis_cache.delete(key)
    return record.user_id
