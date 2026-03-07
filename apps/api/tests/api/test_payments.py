"""
Tests for payment endpoints (/api/v1/payments/*).

Covers:
- GET /plans — list subscription plans
- POST /subscriptions — create subscription
- POST /verify-payment — verify payment completion
- GET /subscription-status — get subscription status
- POST /webhooks/dodo — webhook signature verification
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from tests.conftest import FAKE_USER

PAYMENT_SVC = "app.api.v1.endpoints.payments.payment_service"
WEBHOOK_SVC = "app.api.v1.endpoints.payments.payment_webhook_service"

_NOW = datetime.now(timezone.utc)


class TestGetPlans:
    """GET /api/v1/payments/plans"""

    async def test_list_plans(self, client: AsyncClient):
        from app.models.payment_models import PlanResponse

        mock_plan = PlanResponse(
            id="plan_1",
            dodo_product_id="dodo_1",
            name="Pro",
            amount=1999,
            currency="USD",
            duration="monthly",
            is_active=True,
            created_at=_NOW,
            updated_at=_NOW,
        )
        with patch(
            f"{PAYMENT_SVC}.get_plans",
            new_callable=AsyncMock,
            return_value=[mock_plan],
        ):
            resp = await client.get("/api/v1/payments/plans")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["name"] == "Pro"


class TestCreateSubscription:
    """POST /api/v1/payments/subscriptions"""

    async def test_create_subscription(self, client: AsyncClient):
        mock_resp = {"payment_link": "https://checkout.example.com/abc"}
        with patch(
            f"{PAYMENT_SVC}.create_subscription",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.post(
                "/api/v1/payments/subscriptions",
                json={"product_id": "prod_123", "quantity": 1},
            )

        assert resp.status_code == 200
        assert "payment_link" in resp.json()

    async def test_create_subscription_requires_auth(
        self, unauthed_client: AsyncClient
    ):
        resp = await unauthed_client.post(
            "/api/v1/payments/subscriptions",
            json={"product_id": "prod_123", "quantity": 1},
        )
        assert resp.status_code == 401


class TestVerifyPayment:
    """POST /api/v1/payments/verify-payment"""

    async def test_verify_payment(self, client: AsyncClient):
        mock_result = {
            "payment_completed": True,
            "subscription_id": "sub_123",
            "message": "Payment verified",
        }
        with patch(
            f"{PAYMENT_SVC}.verify_payment_completion",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.post("/api/v1/payments/verify-payment")

        assert resp.status_code == 200
        assert resp.json()["payment_completed"] is True


class TestSubscriptionStatus:
    """GET /api/v1/payments/subscription-status"""

    async def test_get_status(self, client: AsyncClient):
        from app.models.payment_models import UserSubscriptionStatus

        mock_status = UserSubscriptionStatus(
            user_id=FAKE_USER["user_id"],
            is_subscribed=True,
            days_remaining=25,
        )
        with patch(
            f"{PAYMENT_SVC}.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            resp = await client.get("/api/v1/payments/subscription-status")

        assert resp.status_code == 200
        assert resp.json()["is_subscribed"] is True

    async def test_status_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get("/api/v1/payments/subscription-status")
        assert resp.status_code == 401


class TestDodoWebhook:
    """POST /api/v1/payments/webhooks/dodo"""

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
        assert "Invalid webhook signature" in resp.json()["detail"]

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
