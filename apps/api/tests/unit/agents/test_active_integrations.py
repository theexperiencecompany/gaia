"""Per-conversation record of in-context activated integrations."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.agents.core.subagents import active_integrations
from app.constants.cache import ACTIVATION_ACTIVE_PREFIX, ACTIVATION_ACTIVE_TTL
from app.constants.log_tags import LogTag
from app.db.redis import RedisCache
from tests.helpers import captured_wide_event


@pytest.fixture
async def redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(RedisCache, "client", client)
    yield client
    await client.aclose()


@pytest.mark.unit
class TestMarkActive:
    async def test_stamp_writes_set_and_refreshes_ttl(
        self, redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await active_integrations.mark_active("c1", "github")

        assert await redis.smembers(f"{ACTIVATION_ACTIVE_PREFIX}c1") == {"github"}
        assert 0 < await redis.ttl(f"{ACTIVATION_ACTIVE_PREFIX}c1") <= ACTIVATION_ACTIVE_TTL

    async def test_no_redis_client_drops_the_stamp_with_a_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(RedisCache, "client", None)

        async with captured_wide_event() as event:
            await active_integrations.mark_active("c1", "github")

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} Activation stamp dropped: no Redis client",
                "integration_id": "github",
            }
        ]


@pytest.mark.unit
class TestGetActive:
    async def test_returns_what_this_conversation_stamped(
        self, redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await active_integrations.mark_active("c1", "github")
        await active_integrations.mark_active("c1", "gmail")
        await active_integrations.mark_active("c2", "notion")

        assert await active_integrations.get_active("c1") == {"github", "gmail"}

    async def test_no_client_means_nothing_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(RedisCache, "client", None)

        assert await active_integrations.get_active("c1") == set()

    async def test_missing_conversation_id_never_touches_redis(self) -> None:
        with patch.object(RedisCache, "client", new=AsyncMock()) as client:
            assert await active_integrations.get_active(None) == set()
            client.smembers.assert_not_awaited()

    async def test_redis_failure_degrades_to_empty_with_a_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = MagicMock()
        client.smembers = AsyncMock(side_effect=ConnectionError("redis down"))
        monkeypatch.setattr(RedisCache, "client", client)

        async with captured_wide_event() as event:
            assert await active_integrations.get_active("c1") == set()

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} Active integrations unreadable; degrading to none",
                "error_type": "ConnectionError",
            }
        ]
