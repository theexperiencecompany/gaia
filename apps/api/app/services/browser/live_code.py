"""Short capability codes for the bot's live-view link.

The code itself is the secret: anyone holding it can watch and drive the
session, so one is minted per handoff, lives only as long as that handoff may
wait, and is revoked the moment the handoff is settled.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TypedDict

from pydantic import TypeAdapter

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_LIVE_CODE_HANDOFF_PREFIX,
    BROWSER_LIVE_CODE_KEY_PREFIX,
    BROWSER_LIVE_CODE_REVOKED_PREFIX,
)
from app.db.redis import redis_cache
from app.schemas.browser import LiveCodeRecord
from app.services.browser.capability_code import CapabilityCodes


class _PubSubMessage(TypedDict):
    """What a subscription yields: a published message, or the confirmation of a (un)subscribe."""

    type: str


_PUBSUB_MESSAGE: TypeAdapter[_PubSubMessage] = TypeAdapter(_PubSubMessage)
_CODES = CapabilityCodes(
    BROWSER_LIVE_CODE_KEY_PREFIX, LiveCodeRecord, entropy_bytes=BROWSER_LIVE_CODE_ENTROPY_BYTES
)


def _handoff_key(handoff_id: str) -> str:
    return f"{BROWSER_LIVE_CODE_HANDOFF_PREFIX}{handoff_id}"


def _revoked_channel(code: str) -> str:
    return f"{BROWSER_LIVE_CODE_REVOKED_PREFIX}{code}"


async def mint_live_code(session_id: str, user_id: str, handoff_id: str) -> str:
    """Create a short code that opens the session for its owner while this handoff waits."""
    ttl: int = settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
    code = await _CODES.mint(
        LiveCodeRecord(session_id=session_id, user_id=user_id, handoff_id=handoff_id), ttl=ttl
    )
    await redis_cache.client.set(_handoff_key(handoff_id), code, ex=ttl)
    return code


async def revoke_handoff_live_code(handoff_id: str) -> None:
    """Close the link minted for this handoff, if one was: it is settled, so nobody is to act in that browser now."""
    code = await redis_cache.client.getdel(_handoff_key(handoff_id))
    if code is not None:
        await _CODES.revoke(code)
        # A socket the code opened is still streaming and taking input: tell it to close.
        await redis_cache.client.publish(_revoked_channel(code), handoff_id)


async def resolve_live_code(code: str) -> LiveCodeRecord | None:
    """Return the session and owner a code opens, or None if unknown, expired or revoked."""
    return await _CODES.resolve(code)


async def live_code_ended(code: str) -> None:
    """Return once the code is revoked or has lapsed: a socket it opened closes then."""
    pubsub = redis_cache.client.pubsub()
    await pubsub.subscribe(_revoked_channel(code))
    try:
        # Read after subscribing, so a revoke landing in between is not missed.
        remaining = await _CODES.seconds_left(code)
        if remaining is None:
            return
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(remaining):
                async for raw in pubsub.listen():
                    message: _PubSubMessage = _PUBSUB_MESSAGE.validate_python(raw)
                    if message["type"] == "message":
                        return
    finally:
        # Closing drops the connection, and the subscription with it.
        await pubsub.aclose()
