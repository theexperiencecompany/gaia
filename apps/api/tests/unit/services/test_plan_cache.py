"""The one place the cached plan tier is dropped."""

from unittest.mock import AsyncMock, patch

from app.constants.cache import (
    SUBSCRIPTION_BILLING_DAY_CACHE_PREFIX,
    SUBSCRIPTION_PLAN_CACHE_PREFIX,
)
from app.services.payments.plan_cache import invalidate_plan_cache
from tests.helpers import captured_wide_event


async def test_the_users_own_keys_are_dropped() -> None:
    """A billing change can move the billing day too, so both cached reads go."""
    with patch(
        "app.services.payments.plan_cache.redis_cache.delete", new_callable=AsyncMock
    ) as drop:
        await invalidate_plan_cache("u1")

    assert [c.args for c in drop.await_args_list] == [
        (f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}u1",),
        (f"{SUBSCRIPTION_BILLING_DAY_CACHE_PREFIX}u1",),
    ]


async def test_the_drop_is_recorded_on_the_event_against_the_user() -> None:
    """Webhook paths have no authenticated request for the middleware to attribute the drop to."""
    with patch("app.services.payments.plan_cache.redis_cache.delete", new_callable=AsyncMock):
        async with captured_wide_event() as event:
            await invalidate_plan_cache("u1")

    assert event["user"]["id"] == "u1"
    assert event["payment"]["plan_cache_dropped"] is True
