"""One run per real-world occurrence: several triggers can report the same meeting."""

from redis.exceptions import RedisError

from app.constants.log_tags import LogTag
from app.constants.triggers import TRIGGER_OCCURRENCE_KEY, TRIGGER_OCCURRENCE_TTL_SECONDS
from app.db.redis import redis_cache
from shared.py.wide_events import log


async def claim_occurrence(owner_id: str, occurrence: str) -> bool:
    """Take a workflow's or task's one run for an occurrence; False when another trigger already took it.

    Redis down fires anyway, as batching does: a duplicate reminder beats a missed meeting.
    """
    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.TRIGGER} Redis unavailable — occurrence dedupe skipped")
        return True
    key = TRIGGER_OCCURRENCE_KEY.format(owner_id=owner_id, occurrence=occurrence)
    try:
        claimed = await client.set(
            key,
            "1",  # pragma: no mutate — only the key's presence is read
            nx=True,
            ex=TRIGGER_OCCURRENCE_TTL_SECONDS,
        )
        return bool(claimed)
    except RedisError as exc:
        log.warning(
            f"{LogTag.TRIGGER} Redis write failed — occurrence dedupe skipped",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return True
