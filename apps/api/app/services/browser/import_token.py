"""Short single-use codes for the local session-import CLI.

A code authorises a write, not a view, so it is consumed on redemption: a
leaked code cannot be replayed to overwrite a user's logins twice.
"""

from __future__ import annotations

from app.constants.browser import (
    BROWSER_IMPORT_TOKEN_ENTROPY_BYTES,
    BROWSER_IMPORT_TOKEN_KEY_PREFIX,
    BROWSER_IMPORT_TOKEN_TTL_SECONDS,
)
from app.schemas.browser import ImportTokenRecord
from app.services.browser.capability_code import CapabilityCodes

_CODES = CapabilityCodes(
    BROWSER_IMPORT_TOKEN_KEY_PREFIX,
    ImportTokenRecord,
    entropy_bytes=BROWSER_IMPORT_TOKEN_ENTROPY_BYTES,
)


async def mint_import_token(user_id: str) -> str:
    """Return a single-use code that authorises user_id to upload a browser profile."""
    return await _CODES.mint(
        ImportTokenRecord(user_id=user_id), ttl=BROWSER_IMPORT_TOKEN_TTL_SECONDS
    )


async def consume_import_token(token: str) -> str | None:
    """Return the user a code authorises, or None if unknown, expired, or already used."""
    record = await _CODES.consume(token)
    return None if record is None else record.user_id
