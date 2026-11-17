"""Hold one user's scouts under their own daily cost ceiling, apart from the user's allowance.

A learn reserves its slice of the day's ceiling before it starts, in one atomic increment,
so learns that start together can never overrun it: the ones past the ceiling hand their
slice straight back and wait for tomorrow. The run's accounting books each model call into
its reservation (ScoutSpend is the run's ledger), never into the user's budget windows, so
the brief writer that runs after the scouts is never starved by them. A call that costs
more than the slice books the difference; the learn's unspent slice is handed back when it
ends, failed or not. Once the slice is booked the accounting wall stops the run's next call,
so one learn overruns it by at most one call. The tally is whole micro-dollars per user per UTC day.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.scouts import (
    SCOUT_DAILY_COST_CEILING_USD,
    SCOUT_LEARN_RESERVATION_USD,
    SCOUT_SPEND_KEY,
    SCOUT_SPEND_MICROS_PER_USD,
    SCOUT_SPEND_TTL_SECONDS,
)
from app.db.redis import AsyncRedisCommands, redis_cache
from app.utils.errors import AppError


def _micros(usd: float) -> int:
    return round(usd * SCOUT_SPEND_MICROS_PER_USD)


_CEILING = _micros(SCOUT_DAILY_COST_CEILING_USD)
_RESERVATION = _micros(SCOUT_LEARN_RESERVATION_USD)


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


async def _add(key: str, micros: int) -> int:
    pipe = _client().pipeline()
    pipe.incrby(key, micros)
    pipe.expire(key, SCOUT_SPEND_TTL_SECONDS)
    total, _ttl_set = await pipe.execute()
    return int(total)


@dataclass(slots=True)
class ScoutSpend:
    """One learn's reserved slice of today's scout tally, as the ledger its accounting books into."""

    key: str
    booked: int = 0

    async def book(self, cost_usd: float) -> None:
        """Add a call's cost; only what runs past the reservation reaches the tally."""
        over_before = max(self.booked - _RESERVATION, 0)
        self.booked += _micros(cost_usd)
        extra = max(self.booked - _RESERVATION, 0) - over_before
        if extra:
            await _add(self.key, extra)

    def exhausted(self) -> bool:
        """Whether the learn has booked its whole reservation, so the accounting wall stops it."""
        return self.booked >= _RESERVATION

    async def release(self) -> None:
        """Hand back the part of the reservation the learn did not spend."""
        await _add(self.key, -max(_RESERVATION - self.booked, 0))


async def reserve_learn(user_id: str) -> ScoutSpend | None:
    """Reserve one learn's slice of today's ceiling; None when it would take the tally past it."""
    key = _key(user_id)
    if await _add(key, _RESERVATION) > _CEILING:
        await _add(key, -_RESERVATION)
        return None
    return ScoutSpend(key)
