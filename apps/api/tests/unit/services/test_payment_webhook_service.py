"""Unit tests for ``app.services.payments.payment_webhook_service`` — the
identity-binding paths of subscription activation and metadata lookups."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.webhook_models import (
    DodoBillingData,
    DodoCustomerData,
    DodoSubscriptionData,
    DodoWebhookEvent,
    DodoWebhookEventType,
)
from app.services.payments.payment_webhook_service import PaymentWebhookService

USER_ID = "507f1f77bcf86cd799439011"


def _sub_data(**overrides: object) -> DodoSubscriptionData:
    defaults: dict[str, object] = {
        "subscription_id": "sub_1",
        "product_id": "prod_1",
        "customer": DodoCustomerData(customer_id="cus_1", email="alice@example.com", name="Alice"),
        "billing": DodoBillingData(
            city="SF", country="US", state="CA", street="1 Main", zipcode="94101"
        ),
        "status": "active",
        "currency": "USD",
        "quantity": 1,
        "recurring_pre_tax_amount": 2900,
        "payment_frequency_count": 1,
        "payment_frequency_interval": "month",
        "subscription_period_count": 1,
        "subscription_period_interval": "month",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {"user_id": USER_ID},
    }
    defaults.update(overrides)
    return DodoSubscriptionData.model_validate(defaults)


def _event(data: dict[str, object]) -> DodoWebhookEvent:
    return DodoWebhookEvent(
        business_id="biz_1",
        type=DodoWebhookEventType.SUBSCRIPTION_ACTIVE,
        timestamp="2026-01-01T00:00:00Z",
        data=data,
    )


class TestGetUserEmailFromMetadata:
    async def test_numeric_user_id_is_coerced_not_skipped(self) -> None:
        """We set metadata.user_id as str(user_id) at checkout; a provider-side
        JSON number echo is recovered by str(), not silently dropped."""
        service = PaymentWebhookService()

        class _User:
            email = "alice@example.com"

        user = _User()
        with patch(
            "app.services.payments.payment_webhook_service.user_repository.get",
            new_callable=AsyncMock,
            return_value=user,
        ) as mock_get:
            email = await service._get_user_email_from_metadata({"user_id": 12345})

        assert email == "alice@example.com"
        mock_get.assert_awaited_once_with("12345")

    async def test_missing_user_id_skips_lookup(self) -> None:
        service = PaymentWebhookService()
        with patch(
            "app.services.payments.payment_webhook_service.user_repository.get",
            new_callable=AsyncMock,
        ) as mock_get:
            email = await service._get_user_email_from_metadata({})

        assert email is None
        mock_get.assert_not_awaited()


class TestHandleSubscriptionActive:
    async def test_numeric_metadata_user_id_binds_by_coercion_not_email(self) -> None:
        """A truthy non-str metadata id must stay the identity source — the
        subscription binds to str(metadata.user_id), never to whoever owns the
        customer email."""
        service = PaymentWebhookService()
        sub = _sub_data(metadata={"user_id": 12345})
        event = _event(sub.model_dump())

        with (
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.get_by_dodo_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.create",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.services.payments.payment_webhook_service.user_repository.get_by_email",
                new_callable=AsyncMock,
            ) as mock_by_email,
            patch.object(service, "_send_welcome_email", new_callable=AsyncMock),
            patch(
                "app.services.payments.payment_webhook_service.track_subscription_event"
            ),
        ):
            result = await service._handle_subscription_active(event)

        assert result.status == "processed"
        mock_by_email.assert_not_awaited()
        created = mock_create.await_args.args[0]
        assert created.user_id == "12345"

    async def test_missing_metadata_user_id_falls_back_to_email(self) -> None:
        service = PaymentWebhookService()
        sub = _sub_data(metadata={})
        event = _event(sub.model_dump())

        class _User:
            id = USER_ID

        with (
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.get_by_dodo_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.create",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.services.payments.payment_webhook_service.user_repository.get_by_email",
                new_callable=AsyncMock,
                return_value=_User(),
            ),
            patch.object(service, "_send_welcome_email", new_callable=AsyncMock),
            patch(
                "app.services.payments.payment_webhook_service.track_subscription_event"
            ),
        ):
            result = await service._handle_subscription_active(event)

        assert result.status == "processed"
        assert mock_create.await_args.args[0].user_id == USER_ID
