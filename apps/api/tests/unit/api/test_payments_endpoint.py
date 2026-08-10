"""Unit tests for the payments API endpoints.

Tests cover:
- GET /api/v1/payments/plans
- POST /api/v1/payments/subscriptions
- POST /api/v1/payments/subscriptions/cancel
- POST /api/v1/payments/verify-payment
- GET /api/v1/payments/subscription-status
- POST /api/v1/payments/webhooks/dodo

Each endpoint's service seam is faked; the tests pin the full HTTP contract —
exact response bodies, exact service arguments, and the wide-event log lines —
so a wrong argument, a misrouted error, or a missing audit line fails at the
boundary instead of silently degrading.
"""

from unittest.mock import AsyncMock, call, patch

from fastapi import HTTPException
from httpx import AsyncClient

from app.constants.log_tags import LogTag
from app.models.payment_models import (
    CreateSubscriptionResponse,
    PaymentVerificationResponse,
    PlanType,
    SubscriptionStatus,
    UserSubscriptionStatus,
)
from app.models.webhook_models import DodoWebhookProcessingResult
from tests.conftest import FAKE_USER

PLANS_URL = "/api/v1/payments/plans"
SUBSCRIPTIONS_URL = "/api/v1/payments/subscriptions"
SUBSCRIPTIONS_CANCEL_URL = "/api/v1/payments/subscriptions/cancel"
VERIFY_PAYMENT_URL = "/api/v1/payments/verify-payment"
SUBSCRIPTION_STATUS_URL = "/api/v1/payments/subscription-status"
WEBHOOK_URL = "/api/v1/payments/webhooks/dodo"

USER_ID = FAKE_USER["user_id"]

WEBHOOK_PAYLOAD = '{"type": "subscription.created", "data": {}}'
WEBHOOK_HEADERS = {
    "content-type": "application/json",
    "webhook-id": "wh_123",
    "webhook-timestamp": "1234567890",
    "webhook-signature": "v1,sig_abc",
}


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


def _make_subscription_status(**overrides) -> UserSubscriptionStatus:
    base = {
        "user_id": USER_ID,
        "current_plan": None,
        "subscription": None,
        "is_subscribed": False,
        "days_remaining": None,
        "can_upgrade": True,
        "can_downgrade": False,
        "has_subscription": False,
        "plan_type": PlanType.FREE,
        "status": SubscriptionStatus.PENDING,
    }
    base.update(overrides)
    return UserSubscriptionStatus(**base)


# ---------------------------------------------------------------------------
# GET /plans
# ---------------------------------------------------------------------------


class TestGetPlans:
    """Tests for the get plans endpoint."""

    async def test_get_plans_returns_200(self, client: AsyncClient):
        mock_plans = [_make_plan()]
        with (
            patch(
                "app.services.payments.payment_service.payment_service.get_plans",
                new_callable=AsyncMock,
                return_value=mock_plans,
            ) as mock_get,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.get(PLANS_URL)

        assert response.status_code == 200
        assert response.json() == mock_plans
        mock_get.assert_awaited_once_with(active_only=True)
        mock_log.set.assert_called_once_with(payment={"operation": "get_plans"})

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

    async def test_get_plans_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                "app.services.payments.payment_service.payment_service.get_plans",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.get(PLANS_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to get plans"
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Error getting plans",
            error_type="RuntimeError",
            error="db down",
        )


# ---------------------------------------------------------------------------
# POST /subscriptions
# ---------------------------------------------------------------------------


class TestCreateSubscription:
    """Tests for the create subscription endpoint."""

    async def test_create_subscription_returns_200(self, client: AsyncClient):
        mock_result = CreateSubscriptionResponse(
            subscription_id="sess_abc",
            payment_link="https://pay.example.com/link",
            status="payment_link_created",
        )
        with (
            patch(
                "app.services.payments.payment_service.payment_service.create_subscription",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_create,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(
                SUBSCRIPTIONS_URL,
                json={"product_id": "prod_abc", "quantity": 1},
            )

        assert response.status_code == 200
        assert response.json() == {
            "subscription_id": "sess_abc",
            "payment_link": "https://pay.example.com/link",
            "status": "payment_link_created",
        }
        mock_create.assert_awaited_once_with(USER_ID, "prod_abc", 1)
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID},
            payment={"operation": "create_checkout", "plan_type": "prod_abc"},
        )
        mock_log.audit.assert_called_once_with(
            "subscription checkout created",
            actor=USER_ID,
            resource="prod_abc",
            provider="dodo",
        )

    async def test_create_subscription_default_quantity(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.create_subscription",
            new_callable=AsyncMock,
            return_value=CreateSubscriptionResponse(
                subscription_id="sess_abc",
                payment_link="https://pay.example.com/link",
                status="payment_link_created",
            ),
        ) as mock_create:
            await client.post(
                SUBSCRIPTIONS_URL,
                json={"product_id": "prod_abc"},
            )

        mock_create.assert_awaited_once_with(USER_ID, "prod_abc", 1)

    async def test_create_subscription_custom_quantity(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.create_subscription",
            new_callable=AsyncMock,
            return_value=CreateSubscriptionResponse(
                subscription_id="sess_abc",
                payment_link="https://pay.example.com/link",
                status="payment_link_created",
            ),
        ) as mock_create:
            await client.post(
                SUBSCRIPTIONS_URL,
                json={"product_id": "prod_abc", "quantity": 3},
            )

        mock_create.assert_awaited_once_with(USER_ID, "prod_abc", 3)

    async def test_create_subscription_missing_product_id_returns_422(self, client: AsyncClient):
        response = await client.post(SUBSCRIPTIONS_URL, json={})
        assert response.status_code == 422

    async def test_create_subscription_service_error_returns_500(self, client: AsyncClient):
        """Endpoint catches exceptions and returns 500."""
        with (
            patch(
                "app.services.payments.payment_service.payment_service.create_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Payment gateway error"),
            ) as mock_create,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(
                SUBSCRIPTIONS_URL,
                json={"product_id": "prod_abc"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to create subscription"
        mock_create.assert_awaited_once_with(USER_ID, "prod_abc", 1)
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Error creating subscription",
            user_id=USER_ID,
            product_id="prod_abc",
            error_type="RuntimeError",
            error="Payment gateway error",
        )


# ---------------------------------------------------------------------------
# POST /subscriptions/cancel
# ---------------------------------------------------------------------------


class TestCancelSubscription:
    """Tests for the cancel subscription endpoint."""

    async def test_cancel_subscription_returns_updated_status(self, client: AsyncClient):
        mock_status = _make_subscription_status(
            is_subscribed=True,
            can_downgrade=True,
            has_subscription=True,
            plan_type=PlanType.PRO,
            status=SubscriptionStatus.ACTIVE,
            subscription={
                "dodo_subscription_id": "sub_xyz789",
                "status": "active",
                "cancel_at_next_billing_date": True,
            },
        )
        with (
            patch(
                "app.services.payments.payment_service.payment_service.cancel_subscription",
                new_callable=AsyncMock,
                return_value=mock_status,
            ) as mock_cancel,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(SUBSCRIPTIONS_CANCEL_URL)

        assert response.status_code == 200
        assert response.json() == {
            "user_id": USER_ID,
            "current_plan": None,
            "subscription": {
                "dodo_subscription_id": "sub_xyz789",
                "status": "active",
                "cancel_at_next_billing_date": True,
            },
            "is_subscribed": True,
            "days_remaining": None,
            "can_upgrade": True,
            "can_downgrade": True,
            "has_subscription": True,
            "plan_type": "pro",
            "status": "active",
        }
        mock_cancel.assert_awaited_once_with(USER_ID)
        assert mock_log.set.call_args_list == [
            call(user={"id": USER_ID}, payment={"operation": "cancel_subscription"}),
            call(
                payment={
                    "subscription_id": "sub_xyz789",
                    "status": "active",
                }
            ),
        ]
        mock_log.audit.assert_called_once_with(
            "subscription cancellation requested",
            actor=USER_ID,
            provider="dodo",
        )

    async def test_cancel_subscription_free_user_logs_no_subscription(self, client: AsyncClient):
        mock_status = _make_subscription_status()
        with (
            patch(
                "app.services.payments.payment_service.payment_service.cancel_subscription",
                new_callable=AsyncMock,
                return_value=mock_status,
            ) as mock_cancel,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(SUBSCRIPTIONS_CANCEL_URL)

        assert response.status_code == 200
        assert response.json()["is_subscribed"] is False
        mock_cancel.assert_awaited_once_with(USER_ID)
        assert mock_log.set.call_args_list == [
            call(user={"id": USER_ID}, payment={"operation": "cancel_subscription"}),
            call(payment={"subscription_id": None, "status": None}),
        ]

    async def test_cancel_subscription_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                "app.services.payments.payment_service.payment_service.cancel_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Payment gateway error"),
            ),
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(SUBSCRIPTIONS_CANCEL_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to cancel subscription"
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Error cancelling subscription",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="Payment gateway error",
        )

    async def test_cancel_subscription_propagates_http_errors(self, client: AsyncClient):
        """Service HTTPExceptions (404 no subscription) pass through unchanged."""
        with (
            patch(
                "app.services.payments.payment_service.payment_service.cancel_subscription",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404, detail="No active subscription to cancel"),
            ),
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(SUBSCRIPTIONS_CANCEL_URL)

        assert response.status_code == 404
        assert response.json()["detail"] == "No active subscription to cancel"
        mock_log.error.assert_not_called()
        mock_log.audit.assert_not_called()


# ---------------------------------------------------------------------------
# POST /verify-payment
# ---------------------------------------------------------------------------


class TestVerifyPayment:
    """Tests for the verify payment endpoint."""

    async def test_verify_payment_completed(self, client: AsyncClient):
        with (
            patch(
                "app.services.payments.payment_service.payment_service.verify_payment_completion",
                new_callable=AsyncMock,
                return_value=PaymentVerificationResponse(
                    payment_completed=True,
                    subscription_id="sub_123",
                    message="Payment verified",
                ),
            ) as mock_verify,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(VERIFY_PAYMENT_URL)

        assert response.status_code == 200
        assert response.json() == {
            "payment_completed": True,
            "subscription_id": "sub_123",
            "message": "Payment verified",
        }
        mock_verify.assert_awaited_once_with(USER_ID)
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID},
            payment={"operation": "verify_payment"},
        )
        mock_log.audit.assert_called_once_with(
            "payment verification completed",
            actor=USER_ID,
            provider="dodo",
        )

    async def test_verify_payment_not_completed(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.verify_payment_completion",
            new_callable=AsyncMock,
            return_value=PaymentVerificationResponse(
                payment_completed=False,
                subscription_id=None,
                message="No payment found",
            ),
        ):
            response = await client.post(VERIFY_PAYMENT_URL)

        assert response.status_code == 200
        assert response.json() == {
            "payment_completed": False,
            "subscription_id": None,
            "message": "No payment found",
        }

    async def test_verify_payment_service_error_returns_500(self, client: AsyncClient):
        """Endpoint catches exceptions and returns 500."""
        with (
            patch(
                "app.services.payments.payment_service.payment_service.verify_payment_completion",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB unavailable"),
            ),
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(VERIFY_PAYMENT_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to verify payment"
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Error verifying payment",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB unavailable",
        )


# ---------------------------------------------------------------------------
# GET /subscription-status
# ---------------------------------------------------------------------------


class TestGetSubscriptionStatus:
    """Tests for the get subscription status endpoint."""

    async def test_get_subscription_status_free_user(self, client: AsyncClient):
        with (
            patch(
                "app.services.payments.payment_service.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=_make_subscription_status(),
            ) as mock_status,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.get(SUBSCRIPTION_STATUS_URL)

        assert response.status_code == 200
        assert response.json() == {
            "user_id": USER_ID,
            "current_plan": None,
            "subscription": None,
            "is_subscribed": False,
            "days_remaining": None,
            "can_upgrade": True,
            "can_downgrade": False,
            "has_subscription": False,
            "plan_type": "free",
            "status": "pending",
        }
        mock_status.assert_awaited_once_with(USER_ID)
        mock_log.set.assert_called_once_with(
            user={"id": USER_ID},
            payment={"operation": "get_status"},
        )

    async def test_get_subscription_status_subscribed_user(self, client: AsyncClient):
        mock_status = _make_subscription_status(
            is_subscribed=True,
            days_remaining=25,
            can_downgrade=True,
            has_subscription=True,
            plan_type=PlanType.PRO,
            status=SubscriptionStatus.ACTIVE,
            current_plan={"id": "plan_123", "name": "Pro Monthly"},
            subscription={
                "dodo_subscription_id": "sub_xyz789",
                "status": "active",
            },
        )
        with patch(
            "app.services.payments.payment_service.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            response = await client.get(SUBSCRIPTION_STATUS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["is_subscribed"] is True
        assert data["days_remaining"] == 25
        assert data["plan_type"] == "pro"
        assert data["status"] == "active"
        assert data["subscription"] == {
            "dodo_subscription_id": "sub_xyz789",
            "status": "active",
        }
        assert data["current_plan"] == {"id": "plan_123", "name": "Pro Monthly"}

    async def test_get_subscription_status_service_error_returns_500(self, client: AsyncClient):
        """Exception is caught by endpoint try/except and returns 500."""
        with (
            patch(
                "app.services.payments.payment_service.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Redis unavailable"),
            ),
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            resp = await client.get(SUBSCRIPTION_STATUS_URL)

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to get subscription status"
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Error getting subscription status",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="Redis unavailable",
        )


# ---------------------------------------------------------------------------
# POST /webhooks/dodo
# ---------------------------------------------------------------------------


class TestDodoWebhook:
    """Tests for the Dodo webhook endpoint."""

    async def test_webhook_valid_signature_returns_200(self, client: AsyncClient):
        mock_result = DodoWebhookProcessingResult(
            event_type="subscription.created",
            status="processed",
            message="ok",
        )
        with (
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.verify_webhook_signature",
                return_value=True,
            ) as mock_verify,
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.process_webhook",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_process,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(
                WEBHOOK_URL,
                content=WEBHOOK_PAYLOAD,
                headers=WEBHOOK_HEADERS,
            )

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "event_type": "subscription.created",
            "processing_status": "processed",
            "message": "ok",
        }
        mock_verify.assert_called_once_with(
            WEBHOOK_PAYLOAD,
            {
                "webhook-id": "wh_123",
                "webhook-timestamp": "1234567890",
                "webhook-signature": "v1,sig_abc",
            },
        )
        mock_process.assert_awaited_once_with(
            {"type": "subscription.created", "data": {}},
            "wh_123",
        )
        mock_log.set.assert_called_once_with(
            payment={"operation": "webhook", "webhook_id": "wh_123"}
        )
        mock_log.set_ns.assert_called_once_with("payment", event_type="subscription.created")
        mock_log.audit.assert_called_once_with(
            "payment webhook processed",
            actor="dodo-webhook",
            event_type="subscription.created",
            processing_status="processed",
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.PAYMENT} Webhook processed",
            event_type="subscription.created",
            processing_status="processed",
        )

    async def test_webhook_without_type_logs_unknown_event_type(self, client: AsyncClient):
        mock_result = DodoWebhookProcessingResult(
            event_type="unknown",
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
            ) as mock_process,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(
                WEBHOOK_URL,
                content='{"data": {}}',
                headers=WEBHOOK_HEADERS,
            )

        assert response.status_code == 200
        mock_process.assert_awaited_once_with({"data": {}}, "wh_123")
        mock_log.set_ns.assert_called_once_with("payment", event_type="unknown")

    async def test_webhook_invalid_signature_returns_401(self, client: AsyncClient):
        with (
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.verify_webhook_signature",
                return_value=False,
            ) as mock_verify,
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.process_webhook",
                new_callable=AsyncMock,
            ) as mock_process,
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(
                WEBHOOK_URL,
                content=WEBHOOK_PAYLOAD,
                headers=WEBHOOK_HEADERS,
            )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid webhook signature"
        mock_verify.assert_called_once()
        mock_process.assert_not_awaited()
        mock_log.warning.assert_called_once_with(
            f"{LogTag.PAYMENT} Invalid webhook signature",
            webhook_id="wh_123",
        )
        mock_log.set.assert_called_once_with(
            payment={"operation": "webhook", "webhook_id": "wh_123"}
        )

    async def test_webhook_missing_headers_returns_422(self, client: AsyncClient):
        response = await client.post(
            WEBHOOK_URL,
            content='{"type": "test"}',
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422

    async def test_webhook_invalid_json_returns_400(self, client: AsyncClient):
        with (
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.verify_webhook_signature",
                return_value=True,
            ),
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(
                WEBHOOK_URL,
                content="not-valid-json",
                headers=WEBHOOK_HEADERS,
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid JSON payload"
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Invalid JSON in webhook payload",
            error_type="JSONDecodeError",
        )

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
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(
                WEBHOOK_URL,
                content=WEBHOOK_PAYLOAD,
                headers=WEBHOOK_HEADERS,
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Webhook processing failed"
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Error processing webhook",
            error_type="RuntimeError",
            error="processing failed",
        )
