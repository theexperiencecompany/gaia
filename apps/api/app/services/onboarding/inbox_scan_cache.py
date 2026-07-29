"""Redis-backed TTL cache for onboarding inbox scans, keyed by (user_id, fmt)."""

from typing import Any, cast

from app.db.redis import get_cache, set_cache

_TTL_SECONDS = 300


def _key(user_id: str, fmt: str) -> str:
    return f"onboarding:inbox_scan:{user_id}:{fmt}"


async def get(user_id: str, fmt: str) -> list[dict[str, Any]] | None:
    # get_cache is typed Any (generic cache wrapper); this key only ever
    # stores what put() writes below: raw Gmail message dicts.
    return cast("list[dict[str, Any]] | None", await get_cache(_key(user_id, fmt)))


async def put(user_id: str, fmt: str, emails: list[dict[str, Any]]) -> None:
    if not emails:
        return
    await set_cache(_key(user_id, fmt), emails, ttl=_TTL_SECONDS)
