"""The daily scout ceiling: what a learn run books, and when the next one may start.

Redis is fakeredis behind the real singleton, so keys, increments and TTLs are real.
"""

from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import fakeredis.aioredis
import pytest
from tests.factories import make_user_id
import time_machine

from app.config.rate_limits import RateLimitPeriod
from app.constants.scouts import SCOUT_DAILY_COST_CEILING_USD, SCOUT_SPEND_TTL_SECONDS
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from app.services.briefing.scouts.spend import ScoutSpend, may_learn
from app.services.cost_budget import _budget_key, get_daily_cost_budget_usd
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
    await redis.set(_budget_key(USER_ID, RateLimitPeriod.DAY), str(usd))


class TestBook:
    async def test_each_booked_call_adds_to_todays_scout_tally(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        spend = ScoutSpend(USER_ID)

        await spend.book(0.02)
        await spend.book(0.01)

        assert float(await fake_redis.get(_SPEND_KEY)) == pytest.approx(0.03)
        assert await fake_redis.ttl(_SPEND_KEY) == SCOUT_SPEND_TTL_SECONDS

    async def test_booking_never_touches_the_users_own_budget_window(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await ScoutSpend(USER_ID).book(0.04)

        assert await fake_redis.get(_budget_key(USER_ID, RateLimitPeriod.DAY)) is None


class TestMayLearn:
    async def test_a_user_with_no_scout_spend_today_may_learn(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        assert await may_learn(USER_ID) is True

    async def test_spend_just_under_the_ceiling_may_learn(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(_SPEND_KEY, str(SCOUT_DAILY_COST_CEILING_USD - 0.001))

        assert await may_learn(USER_ID) is True

    async def test_spend_at_the_ceiling_may_not(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(_SPEND_KEY, str(SCOUT_DAILY_COST_CEILING_USD))

        assert await may_learn(USER_ID) is False

    async def test_yesterdays_spend_does_not_count(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(f"scouts:spend:{USER_ID}:2026-10-21", "1")

        assert await may_learn(USER_ID) is True

    async def test_the_users_own_spend_does_not_hold_scouts_back(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _spent_today(fake_redis, get_daily_cost_budget_usd(PlanType.FREE))

        assert await may_learn(USER_ID) is True


async def test_without_redis_the_ceiling_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_cache, "redis", None)

    with pytest.raises(AppError) as raised:
        await may_learn(USER_ID)

    error = raised.value
    assert (error.message, error.why, error.fix) == (
        "scout spend cannot be read",
        "Redis is unavailable, so the daily scout ceiling cannot be enforced",
        "restore Redis; scouts learn again on the next brief",
    )
