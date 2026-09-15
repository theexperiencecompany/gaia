"""The one place the cached plan tier is dropped."""

from unittest.mock import AsyncMock, patch

from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX
from app.services.payments.plan_cache import invalidate_plan_cache
from tests.helpers import captured_wide_event


async def test_the_users_own_key_is_dropped() -> None:
    with patch(
        "app.services.payments.plan_cache.redis_cache.delete", new_callable=AsyncMock
    ) as drop:
        await invalidate_plan_cache("u1")

    drop.assert_awaited_once_with(f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}u1")


async def test_the_drop_is_recorded_on_the_event_against_the_user() -> None:
    """Every billing change ends here, and the paths that matter most — the
    webhooks — have no authenticated request for the middleware to attribute
    to. Without this the answer to "did the bust run for this user" is nowhere."""
    with patch("app.services.payments.plan_cache.redis_cache.delete", new_callable=AsyncMock):
        async with captured_wide_event() as event:
            await invalidate_plan_cache("u1")

    assert event["user"]["id"] == "u1"
    assert event["payment"]["plan_cache_dropped"] is True
