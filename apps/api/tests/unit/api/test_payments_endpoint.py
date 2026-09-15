"""Unit tests for the payments API endpoints.

Tests cover:
- GET /api/v1/payments/plans
- POST /api/v1/payments/subscriptions
- POST /api/v1/payments/verify-payment
- GET /api/v1/payments/subscription-status
- POST /api/v1/payments/webhooks/dodo
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.constants.log_tags import LogTag
from app.models.payment_models import (
    CheckoutSource,
    CreateSubscriptionResponse,
    PaymentVerificationResponse,
    PlanDuration,
    PlanResponse,
    ProCheckout,
)
from app.services.analytics_service import AnalyticsEvents
from tests.unit.services.conftest import SUBSCRIPTION_DATA_PAYLOAD, _make_webhook_event

PLANS_URL = "/api/v1/payments/plans"
SUBSCRIPTIONS_URL = "/api/v1/payments/subscriptions"
CHECKOUT_SESSION_URL = "/api/v1/payments/checkout-session"
SUBSCRIPTIONS_CANCEL_URL = "/api/v1/payments/subscriptions/cancel"
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


class TestCreateSubscription:
    """Tests for the create subscription endpoint."""

    async def test_create_subscription_returns_200(self, client: AsyncClient):
        mock_result = CreateSubscriptionResponse(
            subscription_id="sess_abc",
            payment_link="https://pay.example.com/link",
            status="payment_link_created",
        )
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
        assert data == {
            "subscription_id": "sess_abc",
            "payment_link": "https://pay.example.com/link",
            "status": "payment_link_created",
        }

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
            with patch("app.api.v1.endpoints.payments.capture_context_event") as mock_capture:
                await client.post(
                    SUBSCRIPTIONS_URL,
                    json={"product_id": "prod_abc"},
                )

        mock_create.assert_awaited_once_with("507f1f77bcf86cd799439011", "prod_abc", 1, None)
        # A bundle deployed before `source` existed still checks out; the event
        # carries a null source rather than being silently mis-attributed.
        mock_capture.assert_called_once_with(
            AnalyticsEvents.PAYMENT_CHECKOUT_STARTED,
            {"quantity": 1, "source": None, "surface": "redirect"},
        )

    async def test_create_subscription_attributes_the_redirect_path_to_its_source(
        self, client: AsyncClient
    ):
        """The legacy redirect path emits the same event name as the overlay, so
        the funnel reads one event with a `source`/`surface` split rather than
        two rival events."""
        with patch(
            "app.services.payments.payment_service.payment_service.create_subscription",
            new_callable=AsyncMock,
            return_value=CreateSubscriptionResponse(
                subscription_id="sess_abc",
                payment_link="https://pay.example.com/link",
                status="payment_link_created",
            ),
        ):
            with patch("app.api.v1.endpoints.payments.capture_context_event") as mock_capture:
                response = await client.post(
                    SUBSCRIPTIONS_URL,
                    json={"product_id": "prod_abc", "source": "payment_retry"},
                )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.PAYMENT_CHECKOUT_STARTED,
            {"quantity": 1, "source": "payment_retry", "surface": "redirect"},
        )

    async def test_create_subscription_rejects_an_unknown_source(self, client: AsyncClient):
        response = await client.post(
            SUBSCRIPTIONS_URL, json={"product_id": "prod_abc", "source": "billboard"}
        )
        assert response.status_code == 422

    async def test_create_subscription_forwards_discount_code(self, client: AsyncClient):
        """A code offered in the app (the founder's letter) reaches the checkout session."""
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
                json={"product_id": "prod_abc", "discount_code": "THANKYOU40"},
            )

        mock_create.assert_awaited_once_with(
            "507f1f77bcf86cd799439011", "prod_abc", 1, "THANKYOU40"
        )

    async def test_create_subscription_missing_product_id_returns_422(self, client: AsyncClient):
        response = await client.post(SUBSCRIPTIONS_URL, json={})
        assert response.status_code == 422

    async def test_create_subscription_service_error_returns_500(self, client: AsyncClient):
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

    async def test_create_subscription_propagates_http_errors(self, client: AsyncClient):
        """The service's 409 ("Active subscription exists") reached the client
        as a 500: the blanket handler re-wrapped it, so a second checkout from
        a paying user looked like an outage instead of the conflict it is."""
        from fastapi import HTTPException

        with patch(
            "app.services.payments.payment_service.payment_service.create_subscription",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Active subscription exists"),
        ):
            response = await client.post(SUBSCRIPTIONS_URL, json={"product_id": "prod_abc"})

        assert response.status_code == 409
        assert response.json()["detail"] == "Active subscription exists"


# ---------------------------------------------------------------------------
# POST /checkout-session
# ---------------------------------------------------------------------------


class TestCreateCheckoutSession:
    """The overlay's session endpoint: authenticated, never paywalled (a
    non-subscriber calling it is the entire point)."""

    async def test_returns_the_checkout_url_for_the_requested_cycle(self, client: AsyncClient):
        checkout = CreateSubscriptionResponse(
            subscription_id="sess_overlay",
            payment_link="https://checkout.dodopayments.com/sess_overlay",
            status="payment_link_created",
        )
        with patch(
            "app.services.payments.payment_service.payment_service.create_pro_checkout",
            new_callable=AsyncMock,
            return_value=ProCheckout(plan=PlanResponse(**_make_plan()), checkout=checkout),
        ) as mock_create:
            response = await client.post(
                CHECKOUT_SESSION_URL,
                json={"billing_cycle": "yearly", "source": "pricing_card"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "subscription_id": "sess_overlay",
            "payment_link": "https://checkout.dodopayments.com/sess_overlay",
            "status": "payment_link_created",
        }
        mock_create.assert_awaited_once_with(
            "507f1f77bcf86cd799439011", PlanDuration.YEARLY, CheckoutSource.PRICING_CARD
        )

    async def test_attributes_the_overlay_checkout_to_its_source(self, client: AsyncClient):
        """The server is the single emitter of `payment:checkout_started`; the
        client no longer fires its own rival event, so the attribution the
        funnel reads has to arrive on this call."""
        with patch(
            "app.services.payments.payment_service.payment_service.create_pro_checkout",
            new_callable=AsyncMock,
            return_value=ProCheckout(
                plan=PlanResponse(**_make_plan()),
                checkout=CreateSubscriptionResponse(
                    subscription_id="sess_overlay",
                    payment_link="https://checkout.dodopayments.com/sess_overlay",
                    status="payment_link_created",
                ),
            ),
        ):
            with patch("app.api.v1.endpoints.payments.capture_context_event") as mock_capture:
                await client.post(
                    CHECKOUT_SESSION_URL,
                    json={"billing_cycle": "monthly", "source": "paywall_modal"},
                )

        mock_capture.assert_called_once_with(
            AnalyticsEvents.PAYMENT_CHECKOUT_STARTED,
            {
                "billing_cycle": PlanDuration.MONTHLY,
                "source": "paywall_modal",
                "surface": "overlay",
            },
        )

    async def test_rejects_a_checkout_with_no_source(self, client: AsyncClient):
        """Attribution is not optional on the path that replaced the client
        emitter — an unattributed checkout would silently vanish from the funnel."""
        response = await client.post(CHECKOUT_SESSION_URL, json={"billing_cycle": "monthly"})
        assert response.status_code == 422

    async def test_rejects_an_unknown_source(self, client: AsyncClient):
        response = await client.post(
            CHECKOUT_SESSION_URL, json={"billing_cycle": "monthly", "source": "billboard"}
        )
        assert response.status_code == 422

    async def test_defaults_to_the_monthly_cycle(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.create_pro_checkout",
            new_callable=AsyncMock,
            return_value=ProCheckout(
                plan=PlanResponse(**_make_plan()),
                checkout=CreateSubscriptionResponse(
                    subscription_id="sess_overlay",
                    payment_link="https://checkout.dodopayments.com/sess_overlay",
                    status="payment_link_created",
                ),
            ),
        ) as mock_create:
            await client.post(CHECKOUT_SESSION_URL, json={"source": "checkout_resume"})

        mock_create.assert_awaited_once_with(
            "507f1f77bcf86cd799439011", PlanDuration.MONTHLY, CheckoutSource.CHECKOUT_RESUME
        )

    async def test_rejects_an_unknown_billing_cycle(self, client: AsyncClient):
        response = await client.post(
            CHECKOUT_SESSION_URL, json={"billing_cycle": "weekly", "source": "pricing_card"}
        )
        assert response.status_code == 422

    async def test_requires_authentication(self, unauthed_client: AsyncClient):
        response = await unauthed_client.post(CHECKOUT_SESSION_URL, json={"source": "pricing_card"})
        assert response.status_code in (401, 403)

    async def test_wide_event_carries_the_checkout_request_before_dodo_is_called(
        self, client: AsyncClient
    ):
        """The request context is stamped up front, so a checkout that fails
        inside Dodo still shows who asked for which cycle from where."""
        with (
            patch("app.api.v1.endpoints.payments.log") as mock_log,
            patch(
                "app.services.payments.payment_service.payment_service.create_pro_checkout",
                new_callable=AsyncMock,
                return_value=ProCheckout(
                    plan=PlanResponse(**_make_plan()),
                    checkout=CreateSubscriptionResponse(
                        subscription_id="sess_overlay",
                        payment_link="https://checkout.dodopayments.com/sess_overlay",
                        status="payment_link_created",
                    ),
                ),
            ),
        ):
            response = await client.post(
                CHECKOUT_SESSION_URL,
                json={"billing_cycle": "yearly", "source": "pricing_card"},
            )

        assert response.status_code == 200
        mock_log.set.assert_called_once_with(
            user={"id": "507f1f77bcf86cd799439011"},
            payment={
                "operation": "create_checkout_session",
                "billing_cycle": PlanDuration.YEARLY,
                "source": CheckoutSource.PRICING_CARD,
            },
        )

    async def test_audits_the_minted_session_against_the_plan_it_was_priced_from(
        self, client: AsyncClient
    ):
        """Money moves here: the audit trail has to name the caller, the Dodo
        product they were charged for, and the session id support can look up."""
        with (
            patch("app.api.v1.endpoints.payments.log") as mock_log,
            patch(
                "app.services.payments.payment_service.payment_service.create_pro_checkout",
                new_callable=AsyncMock,
                return_value=ProCheckout(
                    plan=PlanResponse(**_make_plan(dodo_product_id="prod_yearly")),
                    checkout=CreateSubscriptionResponse(
                        subscription_id="sess_overlay",
                        payment_link="https://checkout.dodopayments.com/sess_overlay",
                        status="payment_link_created",
                    ),
                ),
            ),
        ):
            response = await client.post(
                CHECKOUT_SESSION_URL,
                json={"billing_cycle": "monthly", "source": "paywall_modal"},
            )

        assert response.status_code == 200
        mock_log.set_ns.assert_called_once_with("payment", session_id="sess_overlay")
        mock_log.audit.assert_called_once_with(
            "overlay checkout session created",
            actor="507f1f77bcf86cd799439011",
            resource="prod_yearly",
            provider="dodo",
        )


# ---------------------------------------------------------------------------
# POST /subscriptions/cancel
# ---------------------------------------------------------------------------


class TestCancelSubscription:
    """Tests for the cancel subscription endpoint."""

    async def test_cancel_subscription_returns_updated_status(self, client: AsyncClient):
        mock_status = MagicMock(
            **{
                **_make_subscription_status(),
                "is_subscribed": True,
                "subscription": {
                    "dodo_subscription_id": "sub_xyz789",
                    "status": "active",
                    "cancel_at_next_billing_date": True,
                },
            }
        )
        with patch(
            "app.services.payments.payment_service.payment_service.cancel_subscription",
            new_callable=AsyncMock,
            return_value=mock_status,
        ) as mock_cancel:
            with patch("app.api.v1.endpoints.payments.capture_context_event") as mock_capture:
                response = await client.post(SUBSCRIPTIONS_CANCEL_URL)

        assert response.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.SUBSCRIPTION_CANCELLATION_REQUESTED)
        mock_cancel.assert_awaited_once_with("507f1f77bcf86cd799439011")

    async def test_cancel_subscription_service_error_returns_500(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.cancel_subscription",
            new_callable=AsyncMock,
            side_effect=Exception("Payment gateway error"),
        ):
            response = await client.post(SUBSCRIPTIONS_CANCEL_URL)

        assert response.status_code == 500

    async def test_cancel_subscription_propagates_http_errors(self, client: AsyncClient):
        """Service HTTPExceptions (404 no subscription) pass through unchanged."""
        from fastapi import HTTPException

        with patch(
            "app.services.payments.payment_service.payment_service.cancel_subscription",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="No active subscription to cancel"),
        ):
            response = await client.post(SUBSCRIPTIONS_CANCEL_URL)

        assert response.status_code == 404
        assert "No active subscription" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /verify-payment
# ---------------------------------------------------------------------------


class TestVerifyPayment:
    """Tests for the verify payment endpoint."""

    async def test_verify_payment_completed(self, client: AsyncClient):
        with patch(
            "app.services.payments.payment_service.payment_service.verify_payment_completion",
            new_callable=AsyncMock,
            return_value=PaymentVerificationResponse(
                payment_completed=True,
                subscription_id="sub_123",
                message="Payment verified",
            ),
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
            return_value=PaymentVerificationResponse(
                payment_completed=False,
                subscription_id=None,
                message="No payment found",
            ),
        ):
            response = await client.post(VERIFY_PAYMENT_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["payment_completed"] is False

    async def test_verify_payment_hands_the_returned_subscription_to_its_own_user(
        self, client: AsyncClient
    ):
        """The id off Dodo's return URL is forwarded for reconciliation, scoped
        to the authenticated caller — never to whoever the id belongs to."""
        with patch(
            "app.services.payments.payment_service.payment_service.verify_payment_completion",
            new_callable=AsyncMock,
            return_value=PaymentVerificationResponse(
                payment_completed=True,
                subscription_id="sub_returned",
                message="Payment verified",
            ),
        ) as mock_verify:
            response = await client.post(
                VERIFY_PAYMENT_URL, json={"subscription_id": "sub_returned"}
            )

        assert response.status_code == 200
        mock_verify.assert_awaited_once_with(
            "507f1f77bcf86cd799439011", subscription_id="sub_returned"
        )

    async def test_verify_payment_without_a_body_reconciles_nothing(self, client: AsyncClient):
        """A poll with no returned id is the plain webhook-landed check — the
        service is still told there is nothing to reconcile against."""
        with patch(
            "app.services.payments.payment_service.payment_service.verify_payment_completion",
            new_callable=AsyncMock,
            return_value=PaymentVerificationResponse(
                payment_completed=False,
                subscription_id=None,
                message="No payment found",
            ),
        ) as mock_verify:
            response = await client.post(VERIFY_PAYMENT_URL)

        assert response.status_code == 200
        mock_verify.assert_awaited_once_with("507f1f77bcf86cd799439011", subscription_id=None)

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
        mock_status = MagicMock(**_make_subscription_status(is_subscribed=True, days_remaining=25))
        with patch(
            "app.services.payments.payment_service.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            response = await client.get(SUBSCRIPTION_STATUS_URL)

        assert response.status_code == 200

    async def test_get_subscription_status_service_error_returns_500(self, client: AsyncClient):
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

    async def test_a_failed_result_asks_dodo_to_retry_instead_of_acknowledging(
        self, client: AsyncClient
    ):
        """A handler that could not complete leaves the state change owed. A 200
        tells Dodo the delivery landed, so it never resends and the event is
        lost for good — the user who paid is never activated."""
        mock_result = MagicMock(
            event_type="subscription.active",
            status="failed",
            message="User not found",
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
                content='{"type": "subscription.active", "data": {}}',
                headers={
                    "content-type": "application/json",
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,sig_abc",
                },
            )

        assert response.status_code == 503
        assert "User not found" in response.json()["detail"]

    async def test_a_refused_delivery_is_not_narrated_as_processed(self, client: AsyncClient):
        """It used to log "Webhook processed" at info on the way to refusing the
        delivery, so a failure read as a success on every dashboard counting
        them."""
        mock_result = MagicMock(
            event_type="subscription.active",
            status="failed",
            message="User not found",
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
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            await client.post(
                WEBHOOK_URL,
                content='{"type": "subscription.active", "data": {}}',
                headers={
                    "content-type": "application/json",
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,sig_abc",
                },
            )

        # Every field, not just the message. This entry is the only record that
        # a delivery was refused, and it is what a human reads when Dodo stops
        # retrying: which event, what the handler decided, and why. Blanking any
        # one of them left the line looking fine and said nothing — four mutants
        # lived exactly there, under an assertion that only read args[0].
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Webhook not acknowledged; asking Dodo to redeliver",
            event_type="subscription.active",
            processing_status="failed",
            failure_reason="User not found",
        )
        assert not any(
            "Webhook processed" in str(call.args[0]) for call in mock_log.info.call_args_list
        )

    async def test_an_ownerless_activation_is_abandoned_and_its_claim_released(
        self, client: AsyncClient
    ):
        """The whole path, not the two halves: a real ``subscription.active``
        whose owner GAIA cannot resolve is acknowledged (a retry finds the
        same missing user) but left re-drivable by hand — claim released — so
        the user who paid can still be activated once the cause is fixed."""
        # No user id in the metadata, so ownership falls to the customer email.
        ownerless = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        payload = json.dumps(_make_webhook_event("subscription.active", ownerless))

        with (
            patch(
                "app.services.payments.payment_webhook_service.payment_webhook_service.verify_webhook_signature",
                return_value=True,
            ),
            patch(
                "app.services.payments.payment_webhook_service.processed_webhook_repository"
            ) as claims,
            patch("app.services.payments.subscription_events.subscription_repository") as subs,
            patch("app.services.payments.subscription_events.user_repository") as users,
        ):
            claims.claim = AsyncMock(return_value=True)
            claims.record_outcome = AsyncMock()
            claims.release = AsyncMock()
            subs.get_by_dodo_id = AsyncMock(return_value=None)
            subs.create = AsyncMock()
            # ...and that email belongs to no GAIA account.
            users.get_by_email = AsyncMock(return_value=None)

            response = await client.post(
                WEBHOOK_URL,
                content=payload,
                headers={
                    "content-type": "application/json",
                    "webhook-id": "wh_ownerless",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,sig_abc",
                },
            )

        assert response.status_code == 200
        assert response.json()["processing_status"] == "abandoned"
        claims.release.assert_awaited_once_with("wh_ownerless")
        claims.record_outcome.assert_not_awaited()
        subs.create.assert_not_awaited()

    async def test_an_abandoned_delivery_is_acknowledged_and_logged_as_an_error(
        self, client: AsyncClient
    ):
        """A permanent failure — no GAIA user behind the subscription, or a
        lifecycle event for a row that never arrived — must not be answered
        with a 503: Dodo would redeliver it on its retry schedule and every
        redelivery would fail identically. It is acknowledged, and the failure
        is on the wide event at error level, which is what pages someone."""
        mock_result = MagicMock(
            event_type="subscription.active",
            status="abandoned",
            message="User not found",
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
            patch("app.api.v1.endpoints.payments.log") as mock_log,
        ):
            response = await client.post(
                WEBHOOK_URL,
                content='{"type": "subscription.active", "data": {}}',
                headers={
                    "content-type": "application/json",
                    "webhook-id": "wh_123",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,sig_abc",
                },
            )

        assert response.status_code == 200
        assert response.json()["processing_status"] == "abandoned"
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Webhook abandoned; the delivery cannot be completed by a retry",
            event_type="subscription.active",
            processing_status="abandoned",
            failure_reason="User not found",
        )
        assert not any(
            "Webhook processed" in str(call.args[0]) for call in mock_log.info.call_args_list
        )

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
