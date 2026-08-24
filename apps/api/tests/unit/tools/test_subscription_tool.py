"""Unit tests for app.agents.tools.subscription_tool.

Both tools exist so GAIA stops guessing about the user's money, so the tests
pin what actually reaches the model: the real plan, the real price, and a
checkout link that is never minted for someone who is already paying.

The assertions are exact full-output matches on purpose — these strings are
the tool's contract with the model, and the mutation gate treats every
surviving string mutant as a fact the suite never checked.
"""

from datetime import UTC, datetime
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
from shared.py.wide_events import log

MODULE = "app.agents.tools.subscription_tool"
FAKE_USER_ID = "507f1f77bcf86cd799439011"
NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
NO_USER_TEXT = "Could not identify the user, so their billing state is unavailable."


@pytest.fixture(autouse=True)
def _clean_wide_event() -> None:
    log.reset()


def _cfg(user_id: str | None = FAKE_USER_ID) -> dict[str, dict[str, str | None]]:
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


def _pro_checkout(duration: PlanDuration = PlanDuration.MONTHLY, amount: int = 3000) -> ProCheckout:
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

        assert result == "Plan: Free\nSubscribed: no — this user is on the free tier."

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
        ) as service:
            result = await get_subscription_details.coroutine(config=_cfg())

        assert result == (
            "Plan: Pro\n"
            "Subscribed: yes (status: active)\n"
            "Price: 30.00 USD per month\n"
            "Renews on: 2026-04-14T12:00:00Z\n"
            "Recent charges (1):\n"
            "  - 2026-03-14 30.00 USD (succeeded)"
        )
        service.assert_awaited_once_with(FAKE_USER_ID)
        assert log.get()["tool"] == {"name": "get_subscription_details"}
        assert log.get()["payment"] == {
            "operation": "agent_status_read",
            "plan_type": "pro",
            "payment_count": 1,
        }

    async def test_unresolvable_plan_and_status_render_unknown(self) -> None:
        """A subscription whose catalogue row vanished still reports, with the
        gaps rendered as 'unknown' rather than crashing or lying."""
        details = SubscriptionDetails(
            plan_type=PlanType.PRO,
            is_subscribed=True,
            status=None,
            plan_name="Pro",
            amount=3000,
            currency="USD",
            billing_cycle=PlanDuration.MONTHLY,
            payments=[
                PaymentHistoryEntry(
                    payment_id="pay_1",
                    status=None,
                    amount=3000,
                    currency="USD",
                    created_at=NOW,
                )
            ],
        )

        service = AsyncMock(return_value=details)
        with patch(f"{MODULE}.payment_service.get_subscription_details", service):
            result = await get_subscription_details.coroutine(config=_cfg())

        assert result == (
            "Plan: Pro\n"
            "Subscribed: yes (status: unknown)\n"
            "Price: 30.00 USD per month\n"
            "Recent charges (1):\n"
            "  - 2026-03-14 30.00 USD (unknown)"
        )
        service.assert_awaited_once_with(FAKE_USER_ID)

    async def test_price_line_needs_both_amount_and_currency(self) -> None:
        """Half a price (amount without currency) renders no price line at all —
        quoting '30.00 USD per ' would be worse than silence."""
        details = SubscriptionDetails(
            plan_type=PlanType.PRO,
            is_subscribed=True,
            status=SubscriptionStatus.ACTIVE,
            plan_name="Pro",
            amount=3000,
            currency=None,
            billing_cycle=None,
        )

        with patch(
            f"{MODULE}.payment_service.get_subscription_details", AsyncMock(return_value=details)
        ):
            result = await get_subscription_details.coroutine(config=_cfg())

        assert result == (
            "Plan: Pro\nSubscribed: yes (status: active)\nRecent charges: none recorded yet."
        )

    async def test_missing_cycle_still_renders_the_price_without_a_suffix(self) -> None:
        details = SubscriptionDetails(
            plan_type=PlanType.PRO,
            is_subscribed=True,
            status=SubscriptionStatus.ACTIVE,
            plan_name="Pro",
            amount=3000,
            currency="USD",
            billing_cycle=None,
        )

        with patch(
            f"{MODULE}.payment_service.get_subscription_details", AsyncMock(return_value=details)
        ):
            result = await get_subscription_details.coroutine(config=_cfg())

        assert result == (
            "Plan: Pro\n"
            "Subscribed: yes (status: active)\n"
            "Price: 30.00 USD\n"
            "Recent charges: none recorded yet."
        )

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

        assert result == (
            "Plan: Pro\n"
            "Subscribed: yes (status: active)\n"
            "Price: 30.00 USD per month\n"
            "Cancels on: 2026-04-14T12:00:00Z\n"
            "Cancellation is scheduled — Pro access continues until the date above, "
            "then the account returns to Free.\n"
            "Recent charges: none recorded yet."
        )

    async def test_missing_user_never_reaches_the_billing_system(self) -> None:
        service = AsyncMock()
        with patch(f"{MODULE}.payment_service.get_subscription_details", service):
            result = await get_subscription_details.coroutine(config=_cfg(user_id=None))

        assert result == NO_USER_TEXT
        assert service.await_count == 0


class TestCreateUpgradeLink:
    async def test_free_user_gets_a_checkout_link_with_the_live_price(self) -> None:
        status = AsyncMock(
            return_value=UserSubscriptionStatus(user_id=FAKE_USER_ID, is_subscribed=False)
        )
        with (
            patch(f"{MODULE}.payment_service.get_user_subscription_status", status),
            patch(
                f"{MODULE}.payment_service.create_pro_checkout",
                AsyncMock(return_value=_pro_checkout()),
            ),
        ):
            result = await create_upgrade_link.coroutine(config=_cfg())

        assert result == (
            "GAIA Pro — 30.00 USD per month.\n"
            "Includes: Chat on iMessage; Unlimited memories\n"
            "Checkout link (already tied to this user's account): "
            "https://checkout.dodopayments.com/s/cs_1\n"
            "Give them the link as-is. It stays valid for about an hour."
        )
        status.assert_awaited_once_with(FAKE_USER_ID)
        assert log.get()["tool"] == {"name": "create_upgrade_link"}
        # Issued, not attempted: the stamp exists only because a link came back.
        assert log.get()["payment"] == {
            "operation": "agent_upgrade_link",
            "billing_cycle": PlanDuration.MONTHLY,
        }
        assert log.get()["audit"] == [
            {
                "msg": "upgrade checkout link issued",
                "actor": FAKE_USER_ID,
                "payment": {"operation": "agent_upgrade_link"},
            }
        ]

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
        assert result.startswith("GAIA Pro — 300.00 USD per year.")
        assert log.get()["payment"] == {
            "operation": "agent_upgrade_link",
            "billing_cycle": PlanDuration.YEARLY,
        }

    async def test_pro_user_is_told_so_and_no_session_is_minted(self) -> None:
        status = AsyncMock(
            return_value=UserSubscriptionStatus(
                user_id=FAKE_USER_ID, is_subscribed=True, plan_type=PlanType.PRO
            )
        )
        checkout = AsyncMock()
        with (
            patch(f"{MODULE}.payment_service.get_user_subscription_status", status),
            patch(f"{MODULE}.payment_service.create_pro_checkout", checkout),
        ):
            result = await create_upgrade_link.coroutine(config=_cfg())

        assert result == (
            "This user is already on GAIA Pro — no checkout needed. "
            "Tell them that instead of sending a payment link."
        )
        status.assert_awaited_once_with(FAKE_USER_ID)
        checkout.assert_not_awaited()
        # No link was issued, so no issued-stamp may exist on the event.
        assert "payment" not in log.get()
        assert "audit" not in log.get()

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
            pytest.raises(
                RuntimeError, match=r"^Dodo returned a checkout session without a payment link$"
            ),
        ):
            await create_upgrade_link.coroutine(config=_cfg())

        assert "payment" not in log.get()
        assert "audit" not in log.get()

    async def test_missing_user_never_reaches_the_billing_system(self) -> None:
        status = AsyncMock()
        with patch(f"{MODULE}.payment_service.get_user_subscription_status", status):
            result = await create_upgrade_link.coroutine(config=_cfg(user_id=None))

        assert result == NO_USER_TEXT
        assert status.await_count == 0
