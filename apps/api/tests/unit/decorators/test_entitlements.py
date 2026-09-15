"""The paywall gate: require_active_subscription and its helpers.

Distinct from tiered rate limiting — this blocks access outright for a plan
with none at all, rather than capping usage. The 402 wire shape is fixed (the
frontend is built against it), so the contract tests assert the exact body.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.decorators.entitlements import (
    PAYWALL_MESSAGE,
    SubscriptionRequiredException,
    is_paid,
    require_active_subscription,
)
from app.models.payment_models import PlanType
from app.services.analytics_service import AnalyticsEvents

pytestmark = pytest.mark.unit

ENT = "app.decorators.entitlements"
# require_subscription resolves the caller via app.core.request_context.resolve_caller,
# which reads get_authenticated_user from its own module — not re-imported into
# entitlements.py — so tests patch it at the source.
RCX = "app.core.request_context"


def _checkout(payment_link: str) -> MagicMock:
    checkout = MagicMock()
    checkout.checkout.payment_link = payment_link
    return checkout


class TestIsPaid:
    """The one entitlement answer every decision surface reads.

    The cached tier lags a payment by up to its TTL. A cached PRO is trusted;
    a cached FREE is confirmed against the database once, and a live
    subscription found there drops the stale key so the next read is right.
    """

    async def test_a_cached_pro_is_trusted_without_a_database_read(self) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type", AsyncMock(return_value=PlanType.PRO)
            ) as cached,
            patch(f"{ENT}.payment_service.get_user_subscription_status") as fresh,
        ):
            assert await is_paid("u1") is True
        cached.assert_awaited_once_with("u1")
        fresh.assert_not_called()

    async def test_a_cached_free_is_confirmed_from_the_row_and_the_stale_key_dropped(
        self,
    ) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type", AsyncMock(return_value=PlanType.FREE)
            ),
            patch(
                f"{ENT}.payment_service.get_user_subscription_status",
                AsyncMock(return_value=MagicMock(plan_type=PlanType.PRO)),
            ) as fresh,
            patch(f"{ENT}.invalidate_plan_cache", new_callable=AsyncMock) as invalidate,
        ):
            assert await is_paid("u1") is True
        fresh.assert_awaited_once_with("u1")
        invalidate.assert_awaited_once_with("u1")

    async def test_a_free_user_is_refused_and_the_cache_left_alone(self) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type", AsyncMock(return_value=PlanType.FREE)
            ),
            patch(
                f"{ENT}.payment_service.get_user_subscription_status",
                AsyncMock(return_value=MagicMock(plan_type=PlanType.FREE)),
            ),
            patch(f"{ENT}.invalidate_plan_cache", new_callable=AsyncMock) as invalidate,
        ):
            assert await is_paid("u1") is False
        invalidate.assert_not_awaited()


class TestRequireActiveSubscription:
    async def test_pro_user_passes_without_minting_a_checkout_link(self) -> None:
        checkout_mock = AsyncMock()
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.PRO),
            ) as plan,
            patch(f"{ENT}.payment_service.create_pro_checkout", new=checkout_mock),
        ):
            await require_active_subscription("u1", feature="chat")  # must not raise
        checkout_mock.assert_not_called()
        # The plan read is for THIS user; a lost id would read some default tier.
        plan.assert_awaited_once_with("u1")

    async def test_a_cached_free_is_confirmed_from_the_row_before_blocking(self) -> None:
        """The gate runs the same ``is_paid`` rule as every other surface."""
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(
                f"{ENT}.payment_service.get_user_subscription_status",
                AsyncMock(return_value=MagicMock(plan_type=PlanType.PRO)),
            ),
            patch(f"{ENT}.invalidate_plan_cache", new_callable=AsyncMock) as invalidate,
            patch(f"{ENT}.capture_event") as mock_capture,
        ):
            await require_active_subscription("u1", feature="chat")  # must not raise

        invalidate.assert_awaited_once_with("u1")
        mock_capture.assert_not_called()

    async def test_free_user_gets_the_exact_402_wire_contract(self) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(f"{ENT}.settings.PAYWALL_DISCOUNT_CODE", None),
            patch(f"{ENT}.log") as mock_log,
        ):
            with pytest.raises(SubscriptionRequiredException) as exc_info:
                await require_active_subscription("u1", feature="chat_stream_endpoint")

        exc = exc_info.value
        assert exc.status_code == 402
        assert exc.detail == {
            "code": "subscription_required",
            "message": PAYWALL_MESSAGE,
            "checkout_url": None,
            "discount_code": None,
        }
        mock_log.warning.assert_called_once_with(
            "Subscription required, blocking request",
            user={"id": "u1"},
            payment={"operation": "paywall_gate", "feature": "chat_stream_endpoint"},
        )

    async def test_blocking_never_touches_dodo(self) -> None:
        """The deny path costs one cached plan read and nothing else.

        This gate runs on every authenticated request, so anything it does per
        block is paid per blocked request. Minting here put a ``get_plans``
        call, an HTTP round-trip and a Mongo insert on each one, for a
        single-use link the user never asked for.
        """
        checkout_mock = AsyncMock(return_value=_checkout("https://checkout.dodo.test/abc"))
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(f"{ENT}.payment_service.create_pro_checkout", new=checkout_mock),
        ):
            with pytest.raises(SubscriptionRequiredException):
                await require_active_subscription("u1", feature="chat")

        checkout_mock.assert_not_awaited()

    async def test_discount_code_travels_when_configured(self) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(f"{ENT}.settings.PAYWALL_DISCOUNT_CODE", "SAVE20"),
        ):
            with pytest.raises(SubscriptionRequiredException) as exc_info:
                await require_active_subscription("u1", feature="chat")

        assert exc_info.value.detail["discount_code"] == "SAVE20"
        assert exc_info.value.detail["checkout_url"] is None

    async def test_block_is_captured_against_the_blocked_users_own_profile(self) -> None:
        """The paywall event must carry the blocked user's id, not an anonymous
        one — bot and worker paths reach this with no request context, so an
        implicit distinct_id would strand the block on a ghost profile."""
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(f"{ENT}.capture_event") as mock_capture,
        ):
            with pytest.raises(SubscriptionRequiredException):
                await require_active_subscription("u1", feature="get_token")

        mock_capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.PAYWALL_BLOCKED,
            {"feature": "get_token"},
        )

    async def test_pro_user_is_never_captured_as_blocked(self) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.PRO),
            ),
            patch(f"{ENT}.capture_event") as mock_capture,
        ):
            await require_active_subscription("u1", feature="get_token")

        mock_capture.assert_not_called()
