"""The daily scout ceiling: what a learn run is charged, and when the next one may start.

Redis is fakeredis behind the real singleton, so keys, increments and TTLs are real;
only the plan lookup the budget wall makes is answered by a mock.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
from tests.factories import make_user_id
import time_machine

from app.config.rate_limits import RateLimitPeriod
from app.config.settings import settings
from app.constants.scouts import SCOUT_DAILY_COST_CEILING_USD, SCOUT_SPEND_TTL_SECONDS
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from app.services.briefing.scouts.spend import may_learn, tallied_learn
from app.services.cost_budget import _budget_key, get_daily_cost_budget_usd
from app.utils.errors import AppError

USER_ID = make_user_id()
_NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
_SPEND_KEY = f"scouts:spend:{USER_ID}:2026-10-22"

pytestmark = pytest.mark.usefixtures("free_plan", "today")


@pytest.fixture
def free_plan(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "DEV_UNLIMITED_RATE_LIMITS", False)
    with patch(
        "app.services.cost_budget.payment_service.get_cached_plan_type",
        AsyncMock(return_value=PlanType.FREE),
    ):
        yield


@pytest.fixture
def today() -> Iterator[None]:
    with time_machine.travel(_NOW, tick=False):
        yield


async def _spent_today(redis: fakeredis.aioredis.FakeRedis, usd: float) -> None:
    await redis.set(_budget_key(USER_ID, RateLimitPeriod.DAY), str(usd))


class TestTallied:
    async def test_a_learn_is_charged_what_the_users_window_grew_by(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _spent_today(fake_redis, 0.25)

        async with tallied_learn(USER_ID):
            await _spent_today(fake_redis, 0.27)
        async with tallied_learn(USER_ID):
            await _spent_today(fake_redis, 0.28)

        assert float(await fake_redis.get(_SPEND_KEY)) == pytest.approx(0.03)
        assert await fake_redis.ttl(_SPEND_KEY) == SCOUT_SPEND_TTL_SECONDS

    async def test_a_learn_that_raised_is_still_charged(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        async def learn_that_times_out() -> None:
            async with tallied_learn(USER_ID):
                await _spent_today(fake_redis, 0.02)
                raise TimeoutError

        with pytest.raises(TimeoutError):
            await learn_that_times_out()

        assert float(await fake_redis.get(_SPEND_KEY)) == pytest.approx(0.02)

    async def test_a_window_that_rolled_over_mid_learn_charges_nothing(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _spent_today(fake_redis, 0.4)

        async with tallied_learn(USER_ID):
            await fake_redis.delete(_budget_key(USER_ID, RateLimitPeriod.DAY))

        assert float(await fake_redis.get(_SPEND_KEY)) == 0.0


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

    async def test_a_user_past_their_own_budget_wall_may_not(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _spent_today(fake_redis, get_daily_cost_budget_usd(PlanType.FREE))

        assert await may_learn(USER_ID) is False


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
