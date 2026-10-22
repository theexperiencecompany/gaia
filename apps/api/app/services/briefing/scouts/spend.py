"""Hold one user's scout learn runs under a daily cost ceiling.

A learn run's model calls are charged to the user's own daily window by the agent
middleware, so its cost is that window's growth across the run; the growth is tallied
per user per UTC day. Concurrent spend by the same user inflates one run's share, which
only makes the ceiling bite sooner.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.config.rate_limits import RateLimitPeriod
from app.constants.scouts import (
    SCOUT_DAILY_COST_CEILING_USD,
    SCOUT_SPEND_KEY,
    SCOUT_SPEND_TTL_SECONDS,
)
from app.db.redis import AsyncRedisCommands, redis_cache
from app.services.cost_budget import get_budget_stop_reason, get_cost
from app.utils.errors import AppError


def _key(user_id: str) -> str:
    return SCOUT_SPEND_KEY.format(user_id=user_id, day=datetime.now(UTC).date().isoformat())


def _client() -> AsyncRedisCommands:
    client = redis_cache.redis
    if client is None:
        raise AppError(
            message="scout spend cannot be read",
            why="Redis is unavailable, so the daily scout ceiling cannot be enforced",
            fix="restore Redis; scouts learn again on the next brief",
        )
    return client


async def may_learn(user_id: str) -> bool:
    """Whether a learn run fits today: under the scout ceiling and the user's own budget wall."""
    raw = await _client().get(_key(user_id))
    if raw is not None and float(raw) >= SCOUT_DAILY_COST_CEILING_USD:
        return False
    check = await get_budget_stop_reason(user_id, None, None)
    return check.stop_reason is None


@asynccontextmanager
async def tallied_learn(user_id: str) -> AsyncIterator[None]:
    """Run one learn inside, then tally its cost toward today's scout spend, even if it raised."""
    before = await get_cost(user_id, RateLimitPeriod.DAY)
    try:
        yield
    finally:
        cost = max(await get_cost(user_id, RateLimitPeriod.DAY) - before, 0.0)
        key = _key(user_id)
        pipe = _client().pipeline(transaction=False)
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, SCOUT_SPEND_TTL_SECONDS)
        await pipe.execute()
