"""The billing-webhook <-> workflow-pause integration in ``PaymentWebhookService``.

subscription.active / subscription.renewed reactivate paused workflows;
subscription.failed / subscription.on_hold deactivate them. Workflows
deactivated with DeactivationReason.SUBSCRIPTION_LAPSED (cancel, expire,
payment failure, on-hold) were never turned back on when the user
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


@pytest.mark.unit
class TestSubscriptionFailedDeactivatesWorkflows:
    async def test_marks_the_subscription_failed_and_deactivates_workflows(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch.object(
                service, "_deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
            ) as deactivate,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock()
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=USER_ID)

            result = await service._handle_subscription_failed(
                _event(DodoWebhookEventType.SUBSCRIPTION_FAILED, subscription_id="sub_failed")
            )

        sub_repo.apply_update_by_dodo_id.assert_awaited_once()
        call_args = sub_repo.apply_update_by_dodo_id.call_args
        assert call_args.args[0] == "sub_failed"
        assert call_args.args[1].status == "failed"
        deactivate.assert_awaited_once_with(USER_ID)
        assert result.event_type == DodoWebhookEventType.SUBSCRIPTION_FAILED.value
        assert result.status == "processed"
        assert result.message == "Subscription failed"
        assert result.subscription_id == "sub_failed"

    async def test_no_resolvable_user_never_calls_deactivate(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch.object(
                service, "_deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
            ) as deactivate,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock()
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=None)

            await service._handle_subscription_failed(
                _event(DodoWebhookEventType.SUBSCRIPTION_FAILED)
            )

        deactivate.assert_not_awaited()

    async def test_missing_subscription_data_raises(self) -> None:
        service = PaymentWebhookService()
        event = MagicMock(spec=DodoWebhookEvent)
        event.get_subscription_data.return_value = None

        with pytest.raises(ValueError, match="Invalid subscription data"):
            await service._handle_subscription_failed(event)


@pytest.mark.unit
class TestSubscriptionOnHoldDeactivatesWorkflows:
    async def test_marks_the_subscription_on_hold_and_deactivates_workflows(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch.object(
                service, "_deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
            ) as deactivate,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock()
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=USER_ID)

            result = await service._handle_subscription_on_hold(
                _event(DodoWebhookEventType.SUBSCRIPTION_ON_HOLD, subscription_id="sub_hold")
            )

        sub_repo.apply_update_by_dodo_id.assert_awaited_once()
        call_args = sub_repo.apply_update_by_dodo_id.call_args
        assert call_args.args[0] == "sub_hold"
        assert call_args.args[1].status == "on_hold"
        deactivate.assert_awaited_once_with(USER_ID)
        assert result.event_type == DodoWebhookEventType.SUBSCRIPTION_ON_HOLD.value
        assert result.status == "processed"
        assert result.message == "Subscription on hold"
        assert result.subscription_id == "sub_hold"

    async def test_no_resolvable_user_never_calls_deactivate(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch.object(
                service, "_deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
            ) as deactivate,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock()
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=None)

            await service._handle_subscription_on_hold(
                _event(DodoWebhookEventType.SUBSCRIPTION_ON_HOLD)
            )

        deactivate.assert_not_awaited()

    async def test_missing_subscription_data_raises(self) -> None:
        service = PaymentWebhookService()
        event = MagicMock(spec=DodoWebhookEvent)
        event.get_subscription_data.return_value = None

        with pytest.raises(ValueError, match="Invalid subscription data"):
            await service._handle_subscription_on_hold(event)


@pytest.mark.unit
class TestDeactivateWorkflowsWrapperNeverRaises:
    """The private wrapper ``_deactivate_workflows_for_lapsed_subscription`` — a
    workflow-deactivation bug must not turn an otherwise-successful billing
    webhook into a Dodo retry."""

    async def test_delegates_to_the_free_function(self) -> None:
        service = PaymentWebhookService()
        with patch(
            f"{MODULE}.deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
        ) as deactivate:
            await service._deactivate_workflows_for_lapsed_subscription(USER_ID)

        deactivate.assert_awaited_once_with(USER_ID)

    async def test_a_failure_is_swallowed_and_logged_with_exact_context(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(
                f"{MODULE}.deactivate_workflows_for_lapsed_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo exploded"),
            ),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await service._deactivate_workflows_for_lapsed_subscription(USER_ID)  # must not raise

        mock_log.error.assert_called_once_with(
            "[PAYMENT] Failed to deactivate workflows for lapsed subscription",
            error="mongo exploded",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


@pytest.mark.unit
class TestReactivateWorkflowsWrapperNeverRaises:
    """The private wrapper ``_reactivate_workflows_for_restored_subscription`` —
    same swallow-and-log posture as deactivation."""

    async def test_delegates_to_the_free_function(self) -> None:
        service = PaymentWebhookService()
        with patch(
            f"{MODULE}.reactivate_workflows_for_restored_subscription", new_callable=AsyncMock
        ) as reactivate:
            await service._reactivate_workflows_for_restored_subscription(USER_ID)

        reactivate.assert_awaited_once_with(USER_ID)

    async def test_a_failure_is_swallowed_and_logged_with_exact_context(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(
                f"{MODULE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo exploded"),
            ),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await service._reactivate_workflows_for_restored_subscription(USER_ID)  # must not raise

        mock_log.error.assert_called_once_with(
            "[PAYMENT] Failed to reactivate workflows for restored subscription",
            error="mongo exploded",
            error_type="RuntimeError",
            user_id=USER_ID,
        )
