"""subscription.active / subscription.renewed reactivating paused workflows.

Workflows deactivated with DeactivationReason.SUBSCRIPTION_LAPSED (cancel,
expire, payment failure, on-hold) were never turned back on when the user
resubscribed — nothing called ``reactivate_workflows_for_restored_subscription``
from the billing webhook path. See ``app/services/workflow/subscription_pause.py``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.webhook_models import (
    DodoBillingData,
    DodoCustomerData,
    DodoSubscriptionData,
    DodoWebhookEvent,
    DodoWebhookEventType,
)
from app.services.payments.payment_webhook_service import PaymentWebhookService

MODULE = "app.services.payments.payment_webhook_service"

USER_ID = "507f1f77bcf86cd799439011"


def _billing() -> DodoBillingData:
    return DodoBillingData(city="SF", country="US", state="CA", street="1 Main St", zipcode="94105")


def _customer() -> DodoCustomerData:
    return DodoCustomerData(customer_id="cus_1", email="user@example.com", name="Test User")


def _subscription_data(**overrides: object) -> DodoSubscriptionData:
    base: dict = {
        "subscription_id": "sub_123",
        "product_id": "prod_pro",
        "customer": _customer(),
        "billing": _billing(),
        "status": "active",
        "currency": "usd",
        "quantity": 1,
        "recurring_pre_tax_amount": 2000,
        "payment_frequency_count": 1,
        "payment_frequency_interval": "Month",
        "subscription_period_count": 1,
        "subscription_period_interval": "Month",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {"user_id": USER_ID},
    }
    base.update(overrides)
    return DodoSubscriptionData(**base)


def _event(event_type: DodoWebhookEventType, **overrides: object) -> DodoWebhookEvent:
    return DodoWebhookEvent(
        business_id="biz_1",
        type=event_type,
        timestamp="2026-01-01T00:00:00Z",
        data=_subscription_data(**overrides).model_dump(),
    )


@pytest.mark.unit
class TestSubscriptionActiveReactivatesWorkflows:
    async def test_existing_subscription_reactivates_paused_workflows(self) -> None:
        """The common resubscribe path: Dodo re-fires `subscription.active` for a
        subscription row that already exists (early-return branch)."""
        service = PaymentWebhookService()
        existing = MagicMock(user_id=USER_ID)
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch(
                f"{MODULE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ) as reactivate,
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=existing)
            result = await service._handle_subscription_active(
                _event(DodoWebhookEventType.SUBSCRIPTION_ACTIVE)
            )

        assert result.status == "processed"
        reactivate.assert_awaited_once_with(USER_ID)

    async def test_newly_created_subscription_reactivates_paused_workflows(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch(
                f"{MODULE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ) as reactivate,
            patch(f"{MODULE}.track_subscription_event"),
            patch.object(service, "_send_welcome_email", new_callable=AsyncMock),
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            result = await service._handle_subscription_active(
                _event(DodoWebhookEventType.SUBSCRIPTION_ACTIVE)
            )

        assert result.status == "processed"
        reactivate.assert_awaited_once_with(USER_ID)


@pytest.mark.unit
class TestSubscriptionRenewedReactivatesWorkflows:
    async def test_renewal_reactivates_paused_workflows(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch(
                f"{MODULE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ) as reactivate,
            patch(f"{MODULE}.track_subscription_event"),
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock(return_value=True)
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=USER_ID)
            result = await service._handle_subscription_renewed(
                _event(DodoWebhookEventType.SUBSCRIPTION_RENEWED)
            )

        assert result.status == "processed"
        reactivate.assert_awaited_once_with(USER_ID)

    async def test_reactivation_failure_never_fails_the_webhook(self) -> None:
        """Same swallow-and-log posture as deactivation — a reactivation bug must
        not turn an otherwise-successful billing webhook into a Dodo retry."""
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch(
                f"{MODULE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch(f"{MODULE}.track_subscription_event"),
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock(return_value=True)
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=USER_ID)
            result = await service._handle_subscription_renewed(
                _event(DodoWebhookEventType.SUBSCRIPTION_RENEWED)
            )

        assert result.status == "processed"
