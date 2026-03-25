"""Unit tests for the payments API endpoints.

Tests cover:
- GET /api/v1/payments/plans
- POST /api/v1/payments/subscriptions
- POST /api/v1/payments/verify-payment
- GET /api/v1/payments/subscription-status
- POST /api/v1/payments/webhooks/dodo
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

PLANS_URL = "/api/v1/payments/plans"
SUBSCRIPTIONS_URL = "/api/v1/payments/subscriptions"
VERIFY_PAYMENT_URL = "/api/v1/payments/verify-payment"
SUBSCRIPTION_STATUS_URL = "/api/v1/payments/subscription-status"
WEBHOOK_URL = "/api/v1/payments/webhooks/dodo"


def _make_plan(**overrides) -> dict:
    base = {
        "id": "plan_123",
        "dodo_product_id": "prod_abc",
        "name": "Pro Monthly",
        "description": "Pro plan billed monthly",
        "amount": 999,
        "currency": "USD",
        "duration": "monthly",
        "max_users": None,
        "features": ["feature_a", "feature_b"],
        "is_active": True,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def _make_subscription_status(**overrides) -> dict:
    base = {
        "user_id": "507f1f77bcf86cd799439011",
        "current_plan": None,
        "subscription": None,
        "is_subscribed": False,
        "days_remaining": None,
        "can_upgrade": True,
        "can_downgrade": True,
        "has_subscription": None,
        "plan_type": None,
        "status": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# GET /plans
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPlans:
    """Tests for the get plans endpoint."""

    async def test_get_plans_returns_200(self, client: AsyncClient):
        mock_plans = [_make_plan()]
        with patch(
            "app.services.payments.payment_service.payment_service.get_plans",
            new_callable=AsyncMock,
            return_value=mock_plans,
        ):
            response = await client.get(PLANS_URL)

        assert response.status_code == 200

    async def test_get_plans_active_only_default(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.get_plans",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_get:
            await client.get(PLANS_URL)

        mock_get.assert_awaited_once_with(active_only=True)

    async def test_get_plans_active_only_false(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.get_plans",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_get:
            await client.get(PLANS_URL, params={"active_only": "false"})

        mock_get.assert_awaited_once_with(active_only=False)

    async def test_get_plans_empty_list(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.get_plans",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.get(PLANS_URL)

        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# POST /subscriptions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSubscription:
    """Tests for the create subscription endpoint."""

    async def test_create_subscription_returns_200(self, client: AsyncClient):
        mock_result = {"payment_link": "https://pay.example.com/link"}
        with patch(
            "app.services.payments.payment_service.payment_service.create_subscription",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.post(
                SUBSCRIPTIONS_URL,
                json={"product_id": "prod_abc", "quantity": 1},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["payment_link"] == "https://pay.example.com/link"

    async def test_create_subscription_default_quantity(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.create_subscription",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_create:
            await client.post(
                SUBSCRIPTIONS_URL,
                json={"product_id": "prod_abc"},
            )

        mock_create.assert_awaited_once_with("507f1f77bcf86cd799439011", "prod_abc", 1)

    async def test_create_subscription_missing_product_id_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(SUBSCRIPTIONS_URL, json={})
        assert response.status_code == 422

    async def test_create_subscription_service_error_returns_500(
        self, client: AsyncClient
    ):
        """Endpoint catches exceptions and returns 500."""
        with patch(
            "app.services.payments.payment_service.payment_service.create_subscription",
            new_callable=AsyncMock,
            side_effect=Exception("Payment gateway error"),
        ):
            response = await client.post(
                SUBSCRIPTIONS_URL,
                json={"product_id": "prod_abc"},
            )

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /verify-payment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyPayment:
    """Tests for the verify payment endpoint."""

    async def test_verify_payment_completed(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.verify_payment_completion",
            new_callable=AsyncMock,
            return_value={
                "payment_completed": True,
                "subscription_id": "sub_123",
                "message": "Payment verified",
            },
        ):
            response = await client.post(VERIFY_PAYMENT_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["payment_completed"] is True
        assert data["subscription_id"] == "sub_123"

    async def test_verify_payment_not_completed(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.verify_payment_completion",
            new_callable=AsyncMock,
            return_value={
                "payment_completed": False,
                "subscription_id": None,
                "message": "No payment found",
            },
        ):
            response = await client.post(VERIFY_PAYMENT_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["payment_completed"] is False

    async def test_verify_payment_service_error_returns_500(self, client: AsyncClient):
        """Endpoint catches exceptions and returns 500."""
        with patch(
            "app.services.payments.payment_service.payment_service.verify_payment_completion",
            new_callable=AsyncMock,
            side_effect=Exception("DB unavailable"),
        ):
            response = await client.post(VERIFY_PAYMENT_URL)

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /subscription-status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSubscriptionStatus:
    """Tests for the get subscription status endpoint."""

    async def test_get_subscription_status_free_user(self, client: AsyncClient):
        mock_status = MagicMock(**_make_subscription_status())
        with patch(
            "app.services.payments.payment_service.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            response = await client.get(SUBSCRIPTION_STATUS_URL)

        assert response.status_code == 200

    async def test_get_subscription_status_subscribed_user(self, client: AsyncClient):
        mock_status = MagicMock(
            **_make_subscription_status(is_subscribed=True, days_remaining=25)
        )
        with patch(
            "app.services.payments.payment_service.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            response = await client.get(SUBSCRIPTION_STATUS_URL)

        assert response.status_code == 200

    async def test_get_subscription_status_service_error_returns_500(
        self, client: AsyncClient
    ):
        """Exception is caught by endpoint try/except and returns 500."""
        with patch(
            "app.services.payments.payment_service.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            side_effect=Exception("Redis unavailable"),
        ):
            resp = await client.get(SUBSCRIPTION_STATUS_URL)

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /webhooks/dodo
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDodoWebhook:
    """Tests for the Dodo webhook endpoint."""

    async def test_webhook_valid_signature_returns_200(self, client: AsyncClient):
        mock_result = MagicMock(
            event_type="subscription.created",
            status="processed",
            message="ok",
        )
        with (
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.verify_webhook_signature",
                return_value=True,
            ),
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.process_webhook",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            response = await client.post(
                WEBHOOK_URL,
                content='{"type": "subscription.created", "data": {}}',
                headers={
                    "content-type": "application/json",
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,sig_abc",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["event_type"] == "subscription.created"

    async def test_webhook_invalid_signature_returns_401(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_webhook_service.payment_webhook_service.verify_webhook_signature",
            return_value=False,
        ):
            response = await client.post(
                WEBHOOK_URL,
                content='{"type": "subscription.created"}',
                headers={
                    "content-type": "application/json",
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,bad_sig",
                },
            )

        assert response.status_code == 401
        assert "Invalid webhook signature" in response.json()["detail"]

    async def test_webhook_missing_headers_returns_422(self, client: AsyncClient):
        response = await client.post(
            WEBHOOK_URL,
            content='{"type": "test"}',
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422

    async def test_webhook_invalid_json_returns_400(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_webhook_service.payment_webhook_service.verify_webhook_signature",
            return_value=True,
        ):
            response = await client.post(
                WEBHOOK_URL,
                content="not-valid-json",
                headers={
                    "content-type": "application/json",
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,sig_abc",
                },
            )

        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["detail"]

    async def test_webhook_processing_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.verify_webhook_signature",
                return_value=True,
            ),
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.process_webhook",
                new_callable=AsyncMock,
                side_effect=RuntimeError("processing failed"),
            ),
        ):
            response = await client.post(
                WEBHOOK_URL,
                content='{"type": "subscription.created"}',
                headers={
                    "content-type": "application/json",
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,sig_abc",
                },
            )

        assert response.status_code == 500
        assert "Webhook processing failed" in response.json()["detail"]
