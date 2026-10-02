"""Short capability codes: an unguessable code in a link that is itself the authority.

A live-view link, a recap, a run's step frames and the CLI's profile upload are
each opened by a code minted for that one purpose and kept in Redis under the
purpose's own prefix, so whoever holds a code holds exactly that access and
nothing else, for as long as the code lives.
"""

from __future__ import annotations

import secrets
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.db.redis import redis_cache
from app.services.browser.exceptions import BrowserUnavailableError

RecordT = TypeVar("RecordT", bound=BaseModel)


class CapabilityCodes(Generic[RecordT]):
    """The codes of one purpose: each resolves to the record it was minted with."""

    def __init__(self, prefix: str, record: type[RecordT], *, entropy_bytes: int) -> None:
        self._prefix = prefix
        self._record = record
        self._entropy_bytes = entropy_bytes

    def _key(self, code: str) -> str:
        return f"{self._prefix}{code}"

    async def mint(self, record: RecordT, *, ttl: int) -> str:
        """Return a new code that opens record for ttl seconds; raise when Redis did not keep it.

        A code Redis never stored would go out in a link that opens nothing.
        """
        code = secrets.token_urlsafe(self._entropy_bytes)
        if not await redis_cache.set(self._key(code), record, ttl=ttl, model=self._record):
            raise BrowserUnavailableError(f"Could not store a {self._prefix} code.")
        return code

    async def resolve(self, code: str) -> RecordT | None:
        """Return what code opens, or None when it is unknown, expired or revoked."""
        return await redis_cache.get(self._key(code), model=self._record)

    async def consume(self, code: str) -> RecordT | None:
        """Resolve a single-use code and end it in the same step, so two redemptions never both succeed."""
        return await redis_cache.get_and_delete(self._key(code), model=self._record)

    async def revoke(self, code: str) -> None:
        """End code now, before its time runs out."""
        await redis_cache.delete(self._key(code))

    async def seconds_left(self, code: str) -> int | None:
        """Seconds until code lapses, or None when it is already gone."""
        return await redis_cache.ttl_seconds(self._key(code))
