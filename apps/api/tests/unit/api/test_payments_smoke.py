"""
Tests for payment endpoints (/api/v1/payments/*).

Covers:
- GET /plans — list subscription plans
- POST /subscriptions — create subscription
- POST /verify-payment — verify payment completion
- GET /subscription-status — get subscription status
- POST /webhooks/dodo — webhook signature verification
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

PAYMENT_SVC = "app.api.v1.endpoints.payments.payment_service"
WEBHOOK_SVC = "app.api.v1.endpoints.payments.payment_webhook_service"

_NOW = datetime.now(UTC)


class TestCreateSubscription:
    """POST /api/v1/payments/subscriptions."""

    async def test_create_subscription_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/v1/payments/subscriptions",
            json={"product_id": "prod_123", "quantity": 1},
        )
        assert resp.status_code == 401


class TestSubscriptionStatus:
    """GET /api/v1/payments/subscription-status."""

    async def test_status_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get("/api/v1/payments/subscription-status")
        assert resp.status_code == 401


class TestDodoWebhook:
    """POST /api/v1/payments/webhooks/dodo."""

    async def test_valid_webhook(self, client: AsyncClient):
        mock_result = MagicMock(
            event_type="subscription.created",
            status="processed",
            message="OK",
        )
        with (
            patch(
                f"{WEBHOOK_SVC}.verify_webhook_signature",
                return_value=True,
            ),
            patch(
                f"{WEBHOOK_SVC}.process_webhook",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            resp = await client.post(
                "/api/v1/payments/webhooks/dodo",
                content='{"type": "subscription.created"}',
                headers={
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,abc123",
                    "content-type": "application/json",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    async def test_invalid_signature(self, client: AsyncClient):
        with patch(
            f"{WEBHOOK_SVC}.verify_webhook_signature",
            return_value=False,
        ):
            resp = await client.post(
                "/api/v1/payments/webhooks/dodo",
                content='{"type": "subscription.created"}',
                headers={
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,invalid",
                    "content-type": "application/json",
                },
            )

        assert resp.status_code == 401
        assert "Invalid webhook signature" in resp.json()["message"]

    async def test_missing_webhook_headers(self, client: AsyncClient):
        """Webhook endpoint requires signature headers."""
        resp = await client.post(
            "/api/v1/payments/webhooks/dodo",
            content='{"type": "test"}',
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422

    async def test_invalid_json_payload(self, client: AsyncClient):
        with patch(
            f"{WEBHOOK_SVC}.verify_webhook_signature",
            return_value=True,
        ):
            resp = await client.post(
                "/api/v1/payments/webhooks/dodo",
                content="not json",
                headers={
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,abc",
                    "content-type": "application/json",
                },
            )

        assert resp.status_code == 400
