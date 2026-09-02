"""``verify_payment_completion`` reconciling against Dodo when no webhook landed.

The bug: verification only ever read ``get_latest_active_for_user``. A dropped
or rejected ``subscription.active`` webhook therefore left a paying user with
no local subscription row and no path to Pro — ``/payment/success`` told them
the payment had not completed while Dodo happily held their money.

The fix routes the reconciliation through the SAME activation used by the
webhook (``subscription_activation.activate_subscription``), so a recovered
payment and a webhook-delivered one produce identical state. These tests pin
the ownership refusal too: the subscription id arrives in a URL the client
controls, so it is a hint, never an authorisation.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from dodopayments import NotFoundError
import pytest

from app.models.payment_models import SubscriptionDocument
from app.services.payments.payment_service import DodoPaymentService

SERVICE_MODULE = "app.services.payments.payment_service"
ACTIVATION_MODULE = "app.services.payments.subscription_activation"

USER_ID = "507f1f77bcf86cd799439011"
OTHER_USER_ID = "507f1f77bcf86cd799439012"
DODO_SUBSCRIPTION_ID = "sub_reconciled"


def _remote_subscription(**overrides: Any) -> MagicMock:
    """A stand-in for the Dodo SDK's ``Subscription``.

    Only ``model_dump`` matters: the service revalidates whatever the SDK hands
    back into ``DodoSubscriptionData`` rather than trusting attribute access.
    """
    payload: dict[str, Any] = {
        "subscription_id": DODO_SUBSCRIPTION_ID,
        "product_id": "prod_pro",
        "customer": {"customer_id": "cus_1", "email": "alice@example.com", "name": "Alice"},
        # Dodo marks every billing field but `country` optional; a real
        # response routinely omits them.
        "billing": {"country": "US", "city": None, "state": None, "street": None, "zipcode": None},
        "status": "active",
        "currency": "USD",
        "quantity": 1,
        "recurring_pre_tax_amount": 3000,
        "payment_frequency_count": 1,
        "payment_frequency_interval": "Month",
        "subscription_period_count": 1,
        "subscription_period_interval": "Month",
        "created_at": "2026-09-01T00:00:00Z",
        "next_billing_date": "2026-10-01T00:00:00Z",
        "previous_billing_date": "2026-09-01T00:00:00Z",
        "metadata": {"user_id": USER_ID},
    }
    payload.update(overrides)
    remote = MagicMock()
    remote.model_dump.return_value = payload
    return remote


def _activated_row() -> SubscriptionDocument:
    return SubscriptionDocument(
        dodo_subscription_id=DODO_SUBSCRIPTION_ID,
        user_id=USER_ID,
        product_id="prod_pro",
        status="active",
        quantity=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _service(remote: MagicMock | Exception) -> DodoPaymentService:
    service = DodoPaymentService()
    service.client = MagicMock()
    if isinstance(remote, Exception):
        service.client.subscriptions.retrieve.side_effect = remote
    else:
        service.client.subscriptions.retrieve.return_value = remote
    return service


@pytest.mark.unit
class TestVerifyPaymentReconcilesWithDodo:
    @pytest.mark.asyncio
    async def test_activates_through_the_shared_path_when_dodo_says_active(self) -> None:
        service = _service(_remote_subscription())

        with (
            patch(f"{SERVICE_MODULE}.subscription_repository") as service_repo,
            patch(f"{SERVICE_MODULE}.user_repository") as service_users,
            patch(f"{SERVICE_MODULE}.send_pro_subscription_email", new_callable=AsyncMock),
            patch(f"{ACTIVATION_MODULE}.subscription_repository") as activation_repo,
            patch(f"{ACTIVATION_MODULE}.send_welcome_email_safely", new_callable=AsyncMock),
            patch(f"{ACTIVATION_MODULE}.reactivate_workflows_safely", new_callable=AsyncMock),
            patch(f"{ACTIVATION_MODULE}.track_subscription_event"),
        ):
            # No local row until the activation writes one.
            service_repo.get_latest_active_for_user = AsyncMock(
                side_effect=[None, _activated_row()]
            )
            service_users.get = AsyncMock(return_value=None)
            activation_repo.get_by_dodo_id = AsyncMock(return_value=None)
            activation_repo.create = AsyncMock()

            result = await service.verify_payment_completion(
                USER_ID, subscription_id=DODO_SUBSCRIPTION_ID
            )

        assert result.payment_completed is True
        assert result.subscription_id == DODO_SUBSCRIPTION_ID
        # The row was written by the shared activation, not by a second
        # implementation living in the verification path.
        created = activation_repo.create.await_args.args[0]
        assert created.dodo_subscription_id == DODO_SUBSCRIPTION_ID
        assert created.user_id == USER_ID
        assert created.status == "active"

    @pytest.mark.asyncio
    async def test_refuses_a_subscription_owned_by_someone_else(self) -> None:
        service = _service(_remote_subscription(metadata={"user_id": OTHER_USER_ID}))

        with (
            patch(f"{SERVICE_MODULE}.subscription_repository") as service_repo,
            patch(f"{ACTIVATION_MODULE}.subscription_repository") as activation_repo,
        ):
            service_repo.get_latest_active_for_user = AsyncMock(return_value=None)
            activation_repo.create = AsyncMock()

            result = await service.verify_payment_completion(
                USER_ID, subscription_id=DODO_SUBSCRIPTION_ID
            )

        assert result.payment_completed is False
        activation_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_verify_a_subscription_dodo_has_never_heard_of(self) -> None:
        service = _service(
            NotFoundError("not found", response=MagicMock(status_code=404), body=None)
        )

        with (
            patch(f"{SERVICE_MODULE}.subscription_repository") as service_repo,
            patch(f"{ACTIVATION_MODULE}.subscription_repository") as activation_repo,
        ):
            service_repo.get_latest_active_for_user = AsyncMock(return_value=None)
            activation_repo.create = AsyncMock()

            result = await service.verify_payment_completion(USER_ID, subscription_id="sub_forged")

        assert result.payment_completed is False
        activation_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_verify_a_subscription_dodo_reports_inactive(self) -> None:
        service = _service(_remote_subscription(status="failed"))

        with (
            patch(f"{SERVICE_MODULE}.subscription_repository") as service_repo,
            patch(f"{ACTIVATION_MODULE}.subscription_repository") as activation_repo,
        ):
            service_repo.get_latest_active_for_user = AsyncMock(return_value=None)
            activation_repo.create = AsyncMock()

            result = await service.verify_payment_completion(
                USER_ID, subscription_id=DODO_SUBSCRIPTION_ID
            )

        assert result.payment_completed is False
        activation_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_never_calls_dodo_without_a_subscription_id(self) -> None:
        service = _service(_remote_subscription())

        with patch(f"{SERVICE_MODULE}.subscription_repository") as service_repo:
            service_repo.get_latest_active_for_user = AsyncMock(return_value=None)

            result = await service.verify_payment_completion(USER_ID)

        assert result.payment_completed is False
        service.client.subscriptions.retrieve.assert_not_called()
