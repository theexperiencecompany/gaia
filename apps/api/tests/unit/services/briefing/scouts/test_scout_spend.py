"""The daily scout ceiling: what a learn reserves and books, and when the next one may start.

Redis is fakeredis behind the real singleton, so keys, increments and TTLs are real.
"""

import asyncio
from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import fakeredis.aioredis
import pytest
from tests.factories import make_user_id
import time_machine

from app.config.rate_limits import RateLimitPeriod, get_daily_cost_budget_usd
from app.constants.scouts import (
    SCOUT_DAILY_COST_CEILING_USD,
    SCOUT_LEARN_RESERVATION_USD,
    SCOUT_SPEND_MICROS_PER_USD,
    SCOUT_SPEND_TTL_SECONDS,
)
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from app.services.briefing.scouts.spend import ScoutSpend, reserve_learn
from app.services.cost_budget import _budget_key
from app.utils.errors import AppError

USER_ID = make_user_id()
# Still the 21st in New York, already the 22nd in UTC: the day key is UTC's.
_NOW = datetime(2026, 10, 21, 23, 0, tzinfo=ZoneInfo("America/New_York"))
_SPEND_KEY = f"scouts:spend:{USER_ID}:2026-10-22"

pytestmark = pytest.mark.usefixtures("today")


@pytest.fixture
def today() -> Iterator[None]:
    with time_machine.travel(_NOW, tick=False):
        yield


async def _spent_today(redis: fakeredis.aioredis.FakeRedis, usd: float) -> None:
    await redis.set(await _budget_key(USER_ID, RateLimitPeriod.DAY), str(usd))


async def _tally(redis: fakeredis.aioredis.FakeRedis) -> float:
    return int(await redis.get(_SPEND_KEY)) / SCOUT_SPEND_MICROS_PER_USD


def _micros(usd: float) -> str:
    return str(round(usd * SCOUT_SPEND_MICROS_PER_USD))


class TestBook:
    async def test_calls_inside_the_reservation_add_nothing_past_it(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        spend = await reserve_learn(USER_ID)
        assert spend is not None

        await spend.book(SCOUT_LEARN_RESERVATION_USD / 2)

        assert await _tally(fake_redis) == pytest.approx(SCOUT_LEARN_RESERVATION_USD)
        assert await fake_redis.ttl(_SPEND_KEY) == SCOUT_SPEND_TTL_SECONDS

    async def test_a_run_past_its_reservation_books_only_the_excess(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        spend = await reserve_learn(USER_ID)
        assert spend is not None

        await spend.book(SCOUT_LEARN_RESERVATION_USD - 0.001)
        await spend.book(0.003)
        await spend.book(0.002)

        assert await _tally(fake_redis) == pytest.approx(SCOUT_LEARN_RESERVATION_USD + 0.004)

    @pytest.mark.regression
    @pytest.mark.usefixtures("fake_redis")
    async def test_a_learn_is_spent_out_once_its_reservation_is_booked(self) -> None:
        """Booking only recorded: nothing told the run to stop at its slice of the day."""
        spend = await reserve_learn(USER_ID)
        assert spend is not None

        await spend.book(SCOUT_LEARN_RESERVATION_USD / 2)
        assert spend.exhausted() is False
        await spend.book(SCOUT_LEARN_RESERVATION_USD / 2)
        assert spend.exhausted() is True

    @pytest.mark.regression
    @pytest.mark.usefixtures("fake_redis")
    async def test_a_learn_winds_down_before_its_reservation_is_spent(self) -> None:
        """A learn learned of its slice only at the stop, too late to write the report it ran for."""
        spend = await reserve_learn(USER_ID)
        assert spend is not None

        await spend.book(SCOUT_LEARN_RESERVATION_USD * 0.2)
        await spend.book(SCOUT_LEARN_RESERVATION_USD * 0.3)
        assert spend.winding_down() is False
        await spend.book(SCOUT_LEARN_RESERVATION_USD * 0.25)
        assert (spend.winding_down(), spend.exhausted()) == (True, False)

    async def test_release_hands_back_the_unspent_part(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        spend = await reserve_learn(USER_ID)
        assert spend is not None
        await spend.book(0.002)

        await spend.release()

        assert await _tally(fake_redis) == pytest.approx(0.002)

    async def test_release_after_an_overrun_takes_nothing_back(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        spend = await reserve_learn(USER_ID)
        assert spend is not None
        await spend.book(SCOUT_LEARN_RESERVATION_USD + 0.002)

        await spend.release()

        assert await _tally(fake_redis) == pytest.approx(SCOUT_LEARN_RESERVATION_USD + 0.002)

    async def test_booking_never_touches_the_users_own_budget_window(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        spend = await reserve_learn(USER_ID)
        assert spend is not None

        await spend.book(0.04)

        assert await fake_redis.get(await _budget_key(USER_ID, RateLimitPeriod.DAY)) is None


class TestReserve:
    async def test_a_user_with_no_scout_spend_today_may_learn(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        assert await reserve_learn(USER_ID) == ScoutSpend(_SPEND_KEY)

    async def test_a_reservation_that_just_fits_the_ceiling_is_granted(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(
            _SPEND_KEY, _micros(SCOUT_DAILY_COST_CEILING_USD - SCOUT_LEARN_RESERVATION_USD)
        )

        assert await reserve_learn(USER_ID) is not None
        assert await _tally(fake_redis) == pytest.approx(SCOUT_DAILY_COST_CEILING_USD)

    async def test_one_that_would_pass_the_ceiling_is_refused_and_handed_back(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        under = SCOUT_DAILY_COST_CEILING_USD - SCOUT_LEARN_RESERVATION_USD / 2
        await fake_redis.set(_SPEND_KEY, _micros(under))

        assert await reserve_learn(USER_ID) is None
        assert await _tally(fake_redis) == pytest.approx(under)

    async def test_learns_reserving_at_once_get_exactly_what_the_ceiling_holds(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        granted = await asyncio.gather(*(reserve_learn(USER_ID) for _ in range(7)))

        fits = round(SCOUT_DAILY_COST_CEILING_USD / SCOUT_LEARN_RESERVATION_USD)
        assert sum(spend is not None for spend in granted) == fits
        assert await _tally(fake_redis) == pytest.approx(SCOUT_DAILY_COST_CEILING_USD)

    async def test_yesterdays_spend_does_not_count(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(f"scouts:spend:{USER_ID}:2026-10-21", _micros(1))

        assert await reserve_learn(USER_ID) is not None

    async def test_the_users_own_spend_does_not_hold_scouts_back(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _spent_today(fake_redis, get_daily_cost_budget_usd(PlanType.FREE))

        assert await reserve_learn(USER_ID) is not None


async def test_without_redis_the_ceiling_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_cache, "redis", None)

    with pytest.raises(AppError) as raised:
        await reserve_learn(USER_ID)

    error = raised.value
    assert (error.message, error.why, error.fix) == (
        "scout spend cannot be read",
        "Redis is unavailable, so the daily scout ceiling cannot be enforced",
        "restore Redis; scouts learn again on the next brief",
    )
