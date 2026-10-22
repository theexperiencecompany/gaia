"""Hold one user's scouts under their own daily cost ceiling, apart from the user's allowance.

A learn run's accounting books each model call here (ScoutSpend is the run's ledger), never
into the user's budget windows, so the brief writer that runs after the scouts is never
starved by them. The tally is per user per UTC day; a run that fails or times out has
still booked every call it made, so failed learns count toward the ceiling too.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.scouts import (
    SCOUT_DAILY_COST_CEILING_USD,
    SCOUT_SPEND_KEY,
    SCOUT_SPEND_TTL_SECONDS,
)
from app.db.redis import AsyncRedisCommands, redis_cache
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
    """Whether today's scout spend is still under the scout ceiling."""
    raw = await _client().get(_key(user_id))
    return raw is None or float(raw) < SCOUT_DAILY_COST_CEILING_USD


@dataclass(frozen=True, slots=True)
class ScoutSpend:
    """One user's scout tally for today, as the ledger a learn run's accounting books into."""

    user_id: str

    async def book(self, cost_usd: float) -> None:
        key = _key(self.user_id)
        pipe = _client().pipeline()
        pipe.incrbyfloat(key, cost_usd)
        pipe.expire(key, SCOUT_SPEND_TTL_SECONDS)
        await pipe.execute()
