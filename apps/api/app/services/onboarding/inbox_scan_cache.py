"""Redis-backed TTL cache for onboarding inbox scans, keyed by (user_id, fmt)."""

from app.db.redis import get_cache, set_cache

_TTL_SECONDS = 300


def _key(user_id: str, fmt: str) -> str:
    return f"onboarding:inbox_scan:{user_id}:{fmt}"


async def get(user_id: str, fmt: str) -> list[dict] | None:
    return await get_cache(_key(user_id, fmt))


async def put(user_id: str, fmt: str, emails: list[dict]) -> None:
    if not emails:
        return
    await set_cache(_key(user_id, fmt), emails, ttl=_TTL_SECONDS)
