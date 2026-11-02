"""The one-time heads-up before a pro user's monthly allowance runs out.

Redis is real (fakeredis), so the SET NX gate and its TTL are what production
would store. The notification write is the boundary that is stubbed.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.constants.cache import COST_BUDGET_NEAR_NOTIFIED_KEY
from app.constants.llm import MONTHLY_BUDGET_TTL_SECONDS
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.notification.notification_models import NotificationSourceEnum
from app.services import usage_heads_up
from app.services.usage_heads_up import notify_monthly_heads_up_once

USER = "u-heads-up"
WINDOW = "20990115"
RESET = datetime(2099, 2, 15, tzinfo=UTC)


@pytest.fixture
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(redis_cache, "redis", client):
        yield client
    await client.flushall()
    await client.connection_pool.disconnect()


@pytest.fixture
def created() -> Iterator[AsyncMock]:
    """Stub the notification write and answer the allowance window for known users only."""
    notify = AsyncMock()
    with (
        patch.object(usage_heads_up.notification_service, "create_notification", notify),
        patch.object(
            usage_heads_up,
            "monthly_allowance_window",
            AsyncMock(
                side_effect=lambda user_id: {USER: (WINDOW, RESET), "u2": (WINDOW, RESET)}[user_id]
            ),
        ),
    ):
        yield notify


@pytest.mark.unit
@pytest.mark.usefixtures("fake_redis")
class TestMonthlyHeadsUp:
    async def test_fires_once_a_month_not_on_every_request(self, created: AsyncMock) -> None:
        await notify_monthly_heads_up_once(USER)
        await notify_monthly_heads_up_once(USER)

        assert created.await_count == 1

    async def test_tells_the_user_what_stops_and_when_it_comes_back(
        self, created: AsyncMock
    ) -> None:
        await notify_monthly_heads_up_once(USER)

        request = created.await_args.args[0]
        assert request.user_id == USER
        assert request.source == NotificationSourceEnum.USAGE_LIMIT
        assert request.content.title == "Most of this month's usage allowance is used"
        assert request.content.body == (
            "When it runs out, chat, workflows and tracked todos pause "
            "until February 15, when it resets."
        )

    async def test_the_gate_is_this_users_month_and_expires_with_it(
        self, created: AsyncMock, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await notify_monthly_heads_up_once(USER)

        key = COST_BUDGET_NEAR_NOTIFIED_KEY.format(user_id=USER, window=WINDOW)
        assert await fake_redis.get(key) == "1"
        assert 0 < await fake_redis.ttl(key) <= MONTHLY_BUDGET_TTL_SECONDS
        assert await fake_redis.ttl(key) > MONTHLY_BUDGET_TTL_SECONDS - 5

    async def test_each_user_gets_their_own(self, created: AsyncMock) -> None:
        await notify_monthly_heads_up_once(USER)
        await notify_monthly_heads_up_once("u2")

        assert [c.args[0].user_id for c in created.await_args_list] == [USER, "u2"]

    async def test_no_redis_sends_nothing(self, created: AsyncMock) -> None:
        with patch.object(redis_cache, "redis", None):
            await notify_monthly_heads_up_once(USER)

        created.assert_not_awaited()

    async def test_a_failed_write_is_reported_with_its_cause(self, created: AsyncMock) -> None:
        created.side_effect = RuntimeError("mongo down")
        with patch.object(usage_heads_up, "log") as log:
            await notify_monthly_heads_up_once(USER)

        assert log.warning.call_args.args == (f"{LogTag.AGENT} Monthly heads-up notice failed",)
        assert log.warning.call_args.kwargs == {"error": "mongo down", "error_type": "RuntimeError"}
