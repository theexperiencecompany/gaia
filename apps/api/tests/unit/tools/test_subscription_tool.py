"""Unit tests for app.agents.tools.subscription_tool.

Both tools exist so GAIA stops guessing about the user's money, so the tests
pin what actually reaches the model: the real plan, the real price, and a
checkout link that is never minted for someone who is already paying.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.subscription_tool import create_upgrade_link, get_subscription_details
from app.models.payment_models import (
    CreateSubscriptionResponse,
    PaymentHistoryEntry,
    PlanDuration,
    PlanResponse,
    PlanType,
    ProCheckout,
    SubscriptionDetails,
    SubscriptionStatus,
    UserSubscriptionStatus,
)

MODULE = "app.agents.tools.subscription_tool"
FAKE_USER_ID = "507f1f77bcf86cd799439011"
NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


def _cfg(user_id: str | None = FAKE_USER_ID) -> dict[str, Any]:
    return {"configurable": {"user_id": user_id}}


def _pro_plan(duration: PlanDuration = PlanDuration.MONTHLY, amount: int = 3000) -> PlanResponse:
    return PlanResponse(
        id="plan_pro",
        dodo_product_id="prod_pro",
        name="Pro",
        description="For serious users.",
        amount=amount,
        currency="USD",
        duration=duration,
        max_users=1,
        features=["Chat on iMessage", "Unlimited memories"],
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _pro_checkout(
    duration: PlanDuration = PlanDuration.MONTHLY, amount: int = 3000
) -> ProCheckout:
    """One catalogue resolution backing both the quoted price and the session."""
    return ProCheckout(
        plan=_pro_plan(duration, amount),
        checkout=CreateSubscriptionResponse(
            subscription_id="cs_1",
            payment_link="https://checkout.dodopayments.com/s/cs_1",
            status="payment_link_created",
        ),
    )


class TestGetSubscriptionDetails:
    async def test_free_user_is_reported_as_unsubscribed(self) -> None:
        details = SubscriptionDetails(plan_type=PlanType.FREE, is_subscribed=False)

        with patch(
            f"{MODULE}.payment_service.get_subscription_details", AsyncMock(return_value=details)
        ):
            result = await get_subscription_details.coroutine(config=_cfg())

        assert "Free" in result
        assert "Subscribed: no" in result

    async def test_pro_user_gets_price_renewal_and_charges(self) -> None:
        details = SubscriptionDetails(
            plan_type=PlanType.PRO,
            is_subscribed=True,
            status=SubscriptionStatus.ACTIVE,
            plan_name="Pro",
            amount=3000,
            currency="USD",
            billing_cycle=PlanDuration.MONTHLY,
            next_billing_date="2026-04-14T12:00:00Z",
            payments=[
                PaymentHistoryEntry(
                    payment_id="pay_1",
                    status="succeeded",
                    amount=3000,
                    currency="USD",
                    created_at=NOW,
                )
            ],
        )

        with patch(
            f"{MODULE}.payment_service.get_subscription_details", AsyncMock(return_value=details)
        ):
            result = await get_subscription_details.coroutine(config=_cfg())

        assert "Subscribed: yes" in result
        assert "30.00 USD per month" in result
        assert "Renews on: 2026-04-14T12:00:00Z" in result
        assert "2026-03-14 30.00 USD (succeeded)" in result

    async def test_scheduled_cancellation_says_cancels_not_renews(self) -> None:
        details = SubscriptionDetails(
            plan_type=PlanType.PRO,
            is_subscribed=True,
            status=SubscriptionStatus.ACTIVE,
            plan_name="Pro",
            amount=3000,
            currency="USD",
            billing_cycle=PlanDuration.MONTHLY,
            next_billing_date="2026-04-14T12:00:00Z",
            cancel_at_next_billing_date=True,
        )

        with patch(
            f"{MODULE}.payment_service.get_subscription_details", AsyncMock(return_value=details)
        ):
            result = await get_subscription_details.coroutine(config=_cfg())

        assert "Cancels on: 2026-04-14T12:00:00Z" in result
        assert "Renews on" not in result

    async def test_missing_user_never_reaches_the_billing_system(self) -> None:
        service = AsyncMock()
        with patch(f"{MODULE}.payment_service.get_subscription_details", service):
            result = await get_subscription_details.coroutine(config=_cfg(user_id=None))

        assert "Could not identify the user" in result
        service.assert_not_awaited()


class TestCreateUpgradeLink:
    async def test_free_user_gets_a_checkout_link_with_the_live_price(self) -> None:
        with (
            patch(
                f"{MODULE}.payment_service.get_user_subscription_status",
                AsyncMock(
                    return_value=UserSubscriptionStatus(user_id=FAKE_USER_ID, is_subscribed=False)
                ),
            ),
            patch(
                f"{MODULE}.payment_service.create_pro_checkout",
                AsyncMock(return_value=_pro_checkout()),
            ),
        ):
            result = await create_upgrade_link.coroutine(config=_cfg())

        assert "https://checkout.dodopayments.com/s/cs_1" in result
        assert "30.00 USD per month" in result
        assert "Chat on iMessage" in result

    async def test_yearly_cycle_is_passed_through_to_the_service(self) -> None:
        checkout = AsyncMock(return_value=_pro_checkout(PlanDuration.YEARLY, amount=30000))
        with (
            patch(
                f"{MODULE}.payment_service.get_user_subscription_status",
                AsyncMock(
                    return_value=UserSubscriptionStatus(user_id=FAKE_USER_ID, is_subscribed=False)
                ),
            ),
            patch(f"{MODULE}.payment_service.create_pro_checkout", checkout),
        ):
            result = await create_upgrade_link.coroutine(
                config=_cfg(), billing_cycle=PlanDuration.YEARLY
            )

        checkout.assert_awaited_once_with(FAKE_USER_ID, PlanDuration.YEARLY)
        assert "300.00 USD per year" in result

    async def test_pro_user_is_told_so_and_no_session_is_minted(self) -> None:
        checkout = AsyncMock()
        with (
            patch(
                f"{MODULE}.payment_service.get_user_subscription_status",
                AsyncMock(
                    return_value=UserSubscriptionStatus(
                        user_id=FAKE_USER_ID, is_subscribed=True, plan_type=PlanType.PRO
                    )
                ),
            ),
            patch(f"{MODULE}.payment_service.create_pro_checkout", checkout),
        ):
            result = await create_upgrade_link.coroutine(config=_cfg())

        assert "already on GAIA Pro" in result
        checkout.assert_not_awaited()

    async def test_a_session_without_a_link_fails_loudly(self) -> None:
        broken = _pro_checkout()
        broken.checkout.payment_link = None
        with (
            patch(
                f"{MODULE}.payment_service.get_user_subscription_status",
                AsyncMock(
                    return_value=UserSubscriptionStatus(user_id=FAKE_USER_ID, is_subscribed=False)
                ),
            ),
            patch(f"{MODULE}.payment_service.create_pro_checkout", AsyncMock(return_value=broken)),
            pytest.raises(RuntimeError, match="without a payment link"),
        ):
            await create_upgrade_link.coroutine(config=_cfg())

    async def test_missing_user_never_reaches_the_billing_system(self) -> None:
        status = AsyncMock()
        with patch(f"{MODULE}.payment_service.get_user_subscription_status", status):
            result = await create_upgrade_link.coroutine(config=_cfg(user_id=None))

        assert "Could not identify the user" in result
        status.assert_not_awaited()
