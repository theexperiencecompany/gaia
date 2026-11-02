"""The billing day the Pro allowance month is anchored on, read off the subscription and cached."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings
from app.models.payment_models import PlanType, SubscriptionDocument, UserSubscriptionStatus
from app.services.payments import payment_service as payment_service_module
from app.services.payments.payment_service import _billing_day, payment_service
from tests.unit.services.conftest import FAKE_USER_ID, SAMPLE_SUBSCRIPTION


def _subscription(**dates: str | None) -> SubscriptionDocument:
    return SAMPLE_SUBSCRIPTION.model_copy(update=dates)


class TestBillingDay:
    def test_comes_from_the_next_billing_date(self) -> None:
        sub = _subscription(next_billing_date="2026-11-15T12:37:31.558660Z")
        assert _billing_day(sub) == 15

    def test_a_yearly_plan_is_anchored_on_its_billing_day_of_month(self) -> None:
        sub = _subscription(next_billing_date="2027-10-31T08:00:00Z")
        assert _billing_day(sub) == 31

    def test_falls_back_to_the_previous_billing_date(self) -> None:
        sub = _subscription(next_billing_date=None, previous_billing_date="2026-10-09T00:00:00Z")
        assert _billing_day(sub) == 9

    def test_reads_the_day_in_utc(self) -> None:
        sub = _subscription(next_billing_date="2026-11-15T23:30:00-05:00")
        assert _billing_day(sub) == 16

    def test_no_subscription_has_no_billing_day(self) -> None:
        assert _billing_day(None) is None


@pytest.fixture
def cache() -> Iterator[MagicMock]:
    with patch.object(payment_service_module, "redis_cache") as mock_cache:
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        yield mock_cache


@pytest.fixture
def subscription_lookup() -> Iterator[AsyncMock]:
    status = UserSubscriptionStatus(
        user_id=FAKE_USER_ID,
        subscription=_subscription(next_billing_date="2026-11-22T22:45:10Z"),
        is_subscribed=True,
        has_subscription=True,
        plan_type=PlanType.PRO,
    )
    lookup = AsyncMock(return_value=status)
    with patch.object(payment_service, "get_user_subscription_status", lookup):
        yield lookup


class TestCachedBillingDay:
    async def test_a_cache_miss_reads_and_caches_the_billing_day(
        self, cache: MagicMock, subscription_lookup: AsyncMock
    ) -> None:
        assert await payment_service.get_cached_billing_day(FAKE_USER_ID) == 22

        cached = cache.set.await_args.args[1]
        assert cached == {"plan_type": "pro", "billing_day": 22}

    async def test_a_record_cached_before_the_billing_day_existed_is_read_again(
        self, cache: MagicMock, subscription_lookup: AsyncMock
    ) -> None:
        cache.get = AsyncMock(return_value={"plan_type": "pro"})

        assert await payment_service.get_cached_billing_day(FAKE_USER_ID) == 22
        subscription_lookup.assert_awaited_once()

    async def test_a_cached_billing_day_is_served_from_the_cache(
        self, cache: MagicMock, subscription_lookup: AsyncMock
    ) -> None:
        cache.get = AsyncMock(return_value={"plan_type": "pro", "billing_day": 5})

        assert await payment_service.get_cached_billing_day(FAKE_USER_ID) == 5
        subscription_lookup.assert_not_awaited()

    async def test_without_plans_there_is_no_billing_day(
        self, cache: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        cache.get = AsyncMock(side_effect=AssertionError("no cache read"))

        assert await payment_service.get_cached_billing_day(FAKE_USER_ID) is None
