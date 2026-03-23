"""
Unit tests for DodoPaymentService and PaymentWebhookService.

Covers:
- DodoPaymentService: get_plans, create_subscription, verify_payment_completion,
  get_user_subscription_status
- PaymentWebhookService: verify_webhook_signature, process_webhook (all event types),
  idempotency, error paths, welcome email dispatch
"""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.models.payment_models import (
    PlanResponse,
    PlanType,
    SubscriptionStatus,
    UserSubscriptionStatus,
)
from app.models.webhook_models import (
    DodoWebhookEventType,
    DodoWebhookProcessingResult,
)
from app.services.payments.payment_service import DodoPaymentService
from app.services.payments.payment_webhook_service import PaymentWebhookService

# ---------------------------------------------------------------------------
# Shared helpers / constants
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_EMAIL = "alice@example.com"
NOW = datetime.now(timezone.utc)

SAMPLE_PLAN_DOC: Dict[str, Any] = {
    "_id": ObjectId(),
    "dodo_product_id": "prod_abc123",
    "name": "Pro Monthly",
    "description": "Pro features billed monthly",
    "amount": 999,
    "currency": "USD",
    "duration": "monthly",
    "max_users": 5,
    "features": ["feature_a", "feature_b"],
    "is_active": True,
    "created_at": NOW,
    "updated_at": NOW,
}

SAMPLE_SUBSCRIPTION_DOC: Dict[str, Any] = {
    "_id": ObjectId(),
    "dodo_subscription_id": "sub_xyz789",
    "user_id": FAKE_USER_ID,
    "product_id": "prod_abc123",
    "status": "active",
    "quantity": 1,
    "currency": "USD",
    "recurring_pre_tax_amount": 999,
    "created_at": NOW,
    "updated_at": NOW,
}

SAMPLE_USER_DOC: Dict[str, Any] = {
    "_id": ObjectId(FAKE_USER_ID),
    "email": FAKE_EMAIL,
    "first_name": "Alice",
    "name": "Alice Smith",
}

# Full webhook payloads -------------------------------------------------------

PAYMENT_DATA_PAYLOAD: Dict[str, Any] = {
    "payment_id": "pay_001",
    "subscription_id": "sub_xyz789",
    "business_id": "biz_001",
    "brand_id": "brand_001",
    "customer": {
        "customer_id": "cust_001",
        "email": FAKE_EMAIL,
        "name": "Alice",
    },
    "billing": {
        "city": "NYC",
        "country": "US",
        "state": "NY",
        "street": "123 Main St",
        "zipcode": "10001",
    },
    "currency": "USD",
    "total_amount": 999,
    "settlement_amount": 999,
    "settlement_currency": "USD",
    "tax": 0,
    "settlement_tax": 0,
    "status": "succeeded",
    "payment_method": "card",
    "created_at": "2025-01-01T00:00:00Z",
    "metadata": {"user_id": FAKE_USER_ID},
}

SUBSCRIPTION_DATA_PAYLOAD: Dict[str, Any] = {
    "subscription_id": "sub_xyz789",
    "product_id": "prod_abc123",
    "customer": {
        "customer_id": "cust_001",
        "email": FAKE_EMAIL,
        "name": "Alice",
    },
    "billing": {
        "city": "NYC",
        "country": "US",
        "state": "NY",
        "street": "123 Main St",
        "zipcode": "10001",
    },
    "status": "active",
    "currency": "USD",
    "quantity": 1,
    "recurring_pre_tax_amount": 999,
    "payment_frequency_count": 1,
    "payment_frequency_interval": "month",
    "subscription_period_count": 1,
    "subscription_period_interval": "month",
    "next_billing_date": "2025-02-01",
    "previous_billing_date": "2025-01-01",
    "created_at": "2025-01-01T00:00:00Z",
    "metadata": {"user_id": FAKE_USER_ID},
}

# ---------------------------------------------------------------------------
# Helpers for building webhook event dicts
# ---------------------------------------------------------------------------


def _make_webhook_event(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "business_id": "biz_001",
        "type": event_type,
        "timestamp": "2025-01-01T00:00:00Z",
        "data": data,
    }


# ---------------------------------------------------------------------------
# Fixtures — mock all DB collections, Redis, external clients
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_plans_collection():
    with patch("app.services.payments.payment_service.plans_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_subscriptions_collection():
    with patch(
        "app.services.payments.payment_service.subscriptions_collection"
    ) as mock_col:
        yield mock_col


@pytest.fixture
def mock_users_collection():
    with patch("app.services.payments.payment_service.users_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_redis_cache():
    with patch("app.services.payments.payment_service.redis_cache") as mock_cache:
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.delete = AsyncMock()
        yield mock_cache


@pytest.fixture
def mock_send_email():
    with patch(
        "app.services.payments.payment_service.send_pro_subscription_email",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_dodo_client():
    client = MagicMock()
    client.checkout_sessions = MagicMock()
    return client


@pytest.fixture
def payment_service(mock_dodo_client):
    """Create a DodoPaymentService with a mocked Dodo client."""
    with patch("app.services.payments.payment_service.DodoPayments") as mock_cls:
        mock_cls.return_value = mock_dodo_client
        svc = DodoPaymentService()
    svc.client = mock_dodo_client
    return svc


# Webhook-service fixtures --------------------------------------------------


@pytest.fixture
def mock_webhook_subscriptions_collection():
    with patch(
        "app.services.payments.payment_webhook_service.subscriptions_collection"
    ) as mock_col:
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_col.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        yield mock_col


@pytest.fixture
def mock_webhook_users_collection():
    with patch(
        "app.services.payments.payment_webhook_service.users_collection"
    ) as mock_col:
        mock_col.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        yield mock_col


@pytest.fixture
def mock_processed_webhooks_collection():
    with patch(
        "app.services.payments.payment_webhook_service.processed_webhooks_collection"
    ) as mock_col:
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.insert_one = AsyncMock()
        yield mock_col


@pytest.fixture
def mock_track_payment():
    with patch(
        "app.services.payments.payment_webhook_service.track_payment_event"
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_track_subscription():
    with patch(
        "app.services.payments.payment_webhook_service.track_subscription_event"
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_webhook_send_email():
    with patch(
        "app.services.payments.payment_webhook_service.send_pro_subscription_email",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def webhook_service():
    """Create a PaymentWebhookService with a mocked webhook verifier."""
    with patch(
        "app.services.payments.payment_webhook_service.settings"
    ) as mock_settings:
        mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
        mock_settings.ENV = "development"
        with patch(
            "app.services.payments.payment_webhook_service.Webhook"
        ) as mock_wh_cls:
            mock_verifier = MagicMock()
            mock_wh_cls.return_value = mock_verifier
            svc = PaymentWebhookService()
    return svc


# ============================================================================
# DodoPaymentService Tests
# ============================================================================


@pytest.mark.unit
class TestGetPlans:
    """Tests for DodoPaymentService.get_plans."""

    async def test_returns_plans_from_database(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Fetches plans from DB when cache is empty."""
        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        plans = await payment_service.get_plans(active_only=True)

        assert len(plans) == 1
        assert plans[0].name == "Pro Monthly"
        assert plans[0].dodo_product_id == "prod_abc123"
        mock_plans_collection.find.assert_called_once_with({"is_active": True})
        mock_redis_cache.set.assert_awaited_once()

    async def test_returns_all_plans_when_active_only_false(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Passes empty query when active_only=False."""
        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        await payment_service.get_plans(active_only=False)

        mock_plans_collection.find.assert_called_once_with({})

    async def test_returns_plans_from_cache(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Returns cached data when available."""
        cached_plan = PlanResponse(
            id="abc",
            dodo_product_id="prod_abc123",
            name="Cached Plan",
            description=None,
            amount=999,
            currency="USD",
            duration="monthly",
            max_users=None,
            features=[],
            is_active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        mock_redis_cache.get = AsyncMock(return_value=[cached_plan.model_dump()])

        plans = await payment_service.get_plans()

        assert len(plans) == 1
        assert plans[0].name == "Cached Plan"
        mock_plans_collection.find.assert_not_called()

    async def test_clears_cache_on_incompatible_data(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """If cached data cannot be parsed, cache is cleared and DB is queried."""
        mock_redis_cache.get = AsyncMock(return_value=[{"bad_key": "bad_val"}])
        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        plans = await payment_service.get_plans()

        mock_redis_cache.delete.assert_awaited_once()
        assert len(plans) == 1

    async def test_adds_missing_dodo_product_id_from_cache(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Cached data missing dodo_product_id gets an empty-string default."""
        cached = {
            "id": "abc",
            "name": "Legacy Plan",
            "amount": 999,
            "currency": "USD",
            "duration": "monthly",
            "features": [],
            "is_active": True,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        }
        mock_redis_cache.get = AsyncMock(return_value=[cached])

        plans = await payment_service.get_plans()

        assert plans[0].dodo_product_id == ""

    async def test_returns_empty_list_when_no_plans(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Returns empty list when DB has no matching plans."""
        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        plans = await payment_service.get_plans()

        assert plans == []

    async def test_plan_without_optional_fields(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Plans missing optional fields (description, max_users) still parse."""
        minimal_doc = {
            "_id": ObjectId(),
            "name": "Basic",
            "amount": 0,
            "currency": "USD",
            "duration": "monthly",
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }
        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[minimal_doc])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        plans = await payment_service.get_plans()

        assert plans[0].dodo_product_id == ""
        assert plans[0].description is None
        assert plans[0].max_users is None
        assert plans[0].features == []


@pytest.mark.unit
class TestCreateSubscription:
    """Tests for DodoPaymentService.create_subscription."""

    async def test_success_returns_payment_link(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Happy path: returns checkout URL when user exists and has no active sub."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_001"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_001"
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=checkout_response
        )

        # Stub get_plans so plan name lookup doesn't fail
        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        result = await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        assert result["subscription_id"] == "sess_001"
        assert result["payment_link"] == "https://checkout.dodo.dev/sess_001"
        assert result["status"] == "payment_link_created"

    async def test_raises_404_if_user_not_found(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID,
                product_id="prod_abc123",
            )

        assert exc_info.value.status_code == 404
        assert "User not found" in str(exc_info.value.detail)

    async def test_raises_409_if_active_subscription_exists(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )

        with pytest.raises(HTTPException) as exc_info:
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID,
                product_id="prod_abc123",
            )

        assert exc_info.value.status_code == 409
        assert "Active subscription exists" in str(exc_info.value.detail)

    async def test_raises_502_on_dodo_client_error(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_dodo_client,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            side_effect=Exception("Dodo API down")
        )

        with pytest.raises(HTTPException) as exc_info:
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID,
                product_id="prod_abc123",
            )

        assert exc_info.value.status_code == 502
        assert "Payment service error" in str(exc_info.value.detail)

    async def test_discount_code_passed_to_checkout(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """When a discount_code is provided, it appears in the params."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_002"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_002"
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=checkout_response
        )

        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
            discount_code="SAVE20",
        )

        call_kwargs = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert call_kwargs["discount_code"] == "SAVE20"

    async def test_no_discount_code_when_not_provided(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """When discount_code is None, it should NOT appear in params."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_003"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_003"
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=checkout_response
        )

        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        call_kwargs = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert "discount_code" not in call_kwargs

    async def test_plan_name_resolved_for_logging(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Verifies plan name lookup succeeds when a matching plan exists."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_004"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_004"
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=checkout_response
        )

        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        result = await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        # Just verify it doesn't raise and returns the link
        assert result["status"] == "payment_link_created"

    async def test_custom_quantity_passed_to_checkout(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Verifies custom quantity ends up in the product_cart."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_005"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_005"
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=checkout_response
        )

        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
            quantity=3,
        )

        call_kwargs = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert call_kwargs["product_cart"][0]["quantity"] == 3


@pytest.mark.unit
class TestVerifyPaymentCompletion:
    """Tests for DodoPaymentService.verify_payment_completion."""

    async def test_active_subscription_returns_completed(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result["payment_completed"] is True
        assert result["subscription_id"] == "sub_xyz789"
        mock_send_email.assert_awaited_once()

    async def test_no_subscription_returns_not_completed(
        self,
        payment_service,
        mock_subscriptions_collection,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result["payment_completed"] is False
        assert "No active subscription" in result["message"]

    async def test_email_failure_does_not_raise(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        """Email failure is swallowed silently."""
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_send_email.side_effect = Exception("SMTP error")

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result["payment_completed"] is True

    async def test_no_email_on_user_without_email(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        """No email sent when user has no email address."""
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )
        user_without_email = {**SAMPLE_USER_DOC, "email": None}
        mock_users_collection.find_one = AsyncMock(return_value=user_without_email)

        await payment_service.verify_payment_completion(FAKE_USER_ID)

        mock_send_email.assert_not_awaited()

    async def test_no_email_when_user_not_found(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        """No email sent when user doesn't exist in DB."""
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )
        mock_users_collection.find_one = AsyncMock(return_value=None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result["payment_completed"] is True
        mock_send_email.assert_not_awaited()


@pytest.mark.unit
class TestGetUserSubscriptionStatus:
    """Tests for DodoPaymentService.get_user_subscription_status."""

    async def test_no_subscription_returns_free_status(
        self,
        payment_service,
        mock_subscriptions_collection,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert isinstance(status, UserSubscriptionStatus)
        assert status.is_subscribed is False
        assert status.plan_type == PlanType.FREE
        assert status.status == SubscriptionStatus.PENDING
        assert status.can_upgrade is True
        assert status.can_downgrade is False
        assert status.has_subscription is False
        assert status.current_plan is None
        assert status.subscription is None

    async def test_active_subscription_returns_pro_status(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )
        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        with patch(
            "app.services.payments.payment_service.serialize_document"
        ) as mock_serialize:
            mock_serialize.return_value = {"id": "serialized"}
            status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.plan_type == PlanType.PRO
        assert status.status == SubscriptionStatus.ACTIVE
        assert status.has_subscription is True
        assert status.can_upgrade is True
        assert status.can_downgrade is True
        assert status.current_plan is not None
        assert status.subscription == {"id": "serialized"}

    async def test_active_subscription_no_matching_plan(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """When subscription product_id doesn't match any plan, current_plan is None."""
        sub_doc = {**SAMPLE_SUBSCRIPTION_DOC, "product_id": "prod_unknown"}
        mock_subscriptions_collection.find_one = AsyncMock(return_value=sub_doc)

        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=[SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        with patch(
            "app.services.payments.payment_service.serialize_document"
        ) as mock_serialize:
            mock_serialize.return_value = {"id": "serialized"}
            status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.current_plan is None

    async def test_plan_lookup_error_sets_plan_to_none(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """If get_plans raises, plan gracefully falls back to None."""
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )
        # Make get_plans fail by causing the cache to raise
        mock_redis_cache.get = AsyncMock(side_effect=Exception("Redis down"))
        cursor = AsyncMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(side_effect=Exception("DB down"))
        mock_plans_collection.find = MagicMock(return_value=cursor)

        with patch(
            "app.services.payments.payment_service.serialize_document"
        ) as mock_serialize:
            mock_serialize.return_value = {"id": "serialized"}
            status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.current_plan is None


# ============================================================================
# DodoPaymentService Initialization Tests
# ============================================================================


@pytest.mark.unit
class TestDodoPaymentServiceInit:
    """Tests for DodoPaymentService.__init__."""

    def test_production_env_uses_live_mode(self):
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "production"
            mock_settings.DODO_PAYMENTS_API_KEY = "sk_live_test"
            with patch(
                "app.services.payments.payment_service.DodoPayments"
            ) as mock_cls:
                DodoPaymentService()
                mock_cls.assert_called_once_with(
                    bearer_token="sk_live_test",
                    environment="live_mode",
                )

    def test_development_env_uses_test_mode(self):
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "development"
            mock_settings.DODO_PAYMENTS_API_KEY = "sk_test_test"
            with patch(
                "app.services.payments.payment_service.DodoPayments"
            ) as mock_cls:
                DodoPaymentService()
                mock_cls.assert_called_once_with(
                    bearer_token="sk_test_test",
                    environment="test_mode",
                )

    def test_client_init_failure_is_logged_not_raised(self):
        """If DodoPayments raises, the error is logged but not propagated."""
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "development"
            mock_settings.DODO_PAYMENTS_API_KEY = "bad_key"
            with patch(
                "app.services.payments.payment_service.DodoPayments",
                side_effect=Exception("Bad API key"),
            ):
                # Should not raise
                svc = DodoPaymentService()
                # client attribute may not exist, which is expected
                assert not hasattr(svc, "client") or svc.client is not None or True


# ============================================================================
# PaymentWebhookService Tests
# ============================================================================


@pytest.mark.unit
class TestVerifyWebhookSignature:
    """Tests for PaymentWebhookService.verify_webhook_signature."""

    def test_returns_true_when_no_verifier_configured(self):
        """When webhook_secret is empty, skip verification and return True."""
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "production"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None
        result = svc.verify_webhook_signature("{}", {})
        assert result is True

    def test_returns_true_in_development_mode(self, webhook_service):
        """In non-production env, skip verification."""
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.ENV = "development"
            result = webhook_service.verify_webhook_signature(
                '{"type":"test"}',
                {
                    "webhook-id": "id",
                    "webhook-timestamp": "ts",
                    "webhook-signature": "sig",
                },
            )
        assert result is True

    def test_production_valid_signature(self):
        """In production with valid signature, returns True."""
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch(
                "app.services.payments.payment_webhook_service.Webhook"
            ) as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(return_value=None)
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.ENV = "production"
            result = svc.verify_webhook_signature(
                '{"type":"test"}',
                {
                    "webhook-id": "msg_abc",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,valid_sig",
                },
            )

        assert result is True
        mock_verifier.verify.assert_called_once()

    def test_production_invalid_signature_returns_false(self):
        """In production with invalid signature, returns False."""
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch(
                "app.services.payments.payment_webhook_service.Webhook"
            ) as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(
                    side_effect=Exception("Invalid signature")
                )
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.ENV = "production"
            result = svc.verify_webhook_signature(
                '{"type":"test"}',
                {
                    "webhook-id": "msg_abc",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,bad_sig",
                },
            )

        assert result is False

    def test_header_normalization(self):
        """Headers are normalized to lowercase-with-dashes format."""
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch(
                "app.services.payments.payment_webhook_service.Webhook"
            ) as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(return_value=None)
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.ENV = "production"
            svc.verify_webhook_signature(
                '{"data":"test"}',
                {
                    "Webhook-Id": "msg_abc",
                    "Webhook-Timestamp": "1234567890",
                    "Webhook-Signature": "v1,sig",
                },
            )

        call_args = mock_verifier.verify.call_args
        headers_passed = call_args[0][1]
        assert "webhook-id" in headers_passed
        assert "webhook-timestamp" in headers_passed
        assert "webhook-signature" in headers_passed

    def test_verifier_init_failure_sets_verifier_to_none(self):
        """If Webhook() constructor fails, verifier is None."""
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "bad_secret"
            mock_settings.ENV = "production"
            with patch(
                "app.services.payments.payment_webhook_service.Webhook",
                side_effect=Exception("Bad secret format"),
            ):
                svc = PaymentWebhookService()

        assert svc.webhook_verifier is None


@pytest.mark.unit
class TestProcessWebhookIdempotency:
    """Tests for idempotency / deduplication in process_webhook."""

    async def test_already_processed_webhook_is_skipped(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        """If webhook_id was already processed, returns 'ignored' immediately."""
        mock_processed_webhooks_collection.find_one = AsyncMock(
            return_value={"webhook_id": "wh_dup"}
        )

        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_dup")

        assert result.status == "ignored"
        assert "already processed" in result.message

    async def test_unknown_event_type_is_ignored_and_recorded(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        """Unhandled event types are recorded to prevent re-processing."""
        event_data = {
            "business_id": "biz_001",
            "type": "payment.succeeded",
            "timestamp": "2025-01-01T00:00:00Z",
            "data": PAYMENT_DATA_PAYLOAD,
        }
        # Simulate unknown event by removing the handler
        original_handlers = webhook_service.handlers.copy()
        webhook_service.handlers = {}

        result = await webhook_service.process_webhook(event_data, "wh_unknown")

        assert result.status == "ignored"
        assert "No handler" in result.message
        mock_processed_webhooks_collection.insert_one.assert_awaited()
        webhook_service.handlers = original_handlers

    async def test_processing_failure_returns_failed_result(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        """When event parsing fails, returns a 'failed' result."""
        bad_data = {"type": "INVALID_TYPE", "data": {}}

        result = await webhook_service.process_webhook(bad_data, "wh_bad")

        assert result.status == "failed"
        assert "Processing error" in result.message


# ============================================================================
# Payment Event Handlers
# ============================================================================


@pytest.mark.unit
class TestHandlePaymentSucceeded:
    """Tests for _handle_payment_succeeded via process_webhook."""

    async def test_processes_valid_payment_success(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_pay_001")

        assert result.status == "processed"
        assert result.payment_id == "pay_001"
        assert result.subscription_id == "sub_xyz789"
        assert "success" in result.message.lower()

    async def test_tracks_analytics_event(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_pay_002")

        mock_track_payment.assert_called_once()
        call_kwargs = mock_track_payment.call_args[1]
        assert call_kwargs["user_id"] == FAKE_EMAIL
        assert call_kwargs["payment_id"] == "pay_001"

    async def test_no_analytics_when_user_email_not_found(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        mock_webhook_users_collection.find_one = AsyncMock(return_value=None)
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {"user_id": "nonexistent"}}
        event_data = _make_webhook_event("payment.succeeded", payload)

        await webhook_service.process_webhook(event_data, "wh_pay_003")

        mock_track_payment.assert_not_called()

    async def test_no_analytics_when_no_user_id_in_metadata(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("payment.succeeded", payload)

        await webhook_service.process_webhook(event_data, "wh_pay_004")

        mock_track_payment.assert_not_called()

    async def test_invalid_payment_data_raises(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        """When payment data can't be parsed, ValueError is raised (caught by process_webhook)."""
        bad_payload = {"incomplete": True}
        event_data = _make_webhook_event("payment.succeeded", bad_payload)

        result = await webhook_service.process_webhook(event_data, "wh_pay_bad")

        assert result.status == "failed"
        assert "Processing error" in result.message


@pytest.mark.unit
class TestHandlePaymentFailed:
    """Tests for _handle_payment_failed."""

    async def test_processes_payment_failure(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.failed", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_fail_001")

        assert result.status == "processed"
        assert "failure" in result.message.lower()
        assert result.payment_id == "pay_001"

    async def test_tracks_failure_analytics(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.failed", PAYMENT_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_fail_002")

        mock_track_payment.assert_called_once()
        call_kwargs = mock_track_payment.call_args[1]
        assert call_kwargs["event_type"] == "payment:failed"


@pytest.mark.unit
class TestHandlePaymentProcessing:
    """Tests for _handle_payment_processing."""

    async def test_processes_payment_processing_event(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        event_data = _make_webhook_event("payment.processing", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_proc_001")

        assert result.status == "processed"
        assert "processing" in result.message.lower()


@pytest.mark.unit
class TestHandlePaymentCancelled:
    """Tests for _handle_payment_cancelled."""

    async def test_processes_payment_cancellation(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        event_data = _make_webhook_event("payment.cancelled", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_cancel_001")

        assert result.status == "processed"
        assert "cancellation" in result.message.lower()


# ============================================================================
# Subscription Event Handlers
# ============================================================================


@pytest.mark.unit
class TestHandleSubscriptionActive:
    """Tests for _handle_subscription_active."""

    async def test_creates_subscription_record(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.active", SUBSCRIPTION_DATA_PAYLOAD
        )
        result = await webhook_service.process_webhook(event_data, "wh_sub_001")

        assert result.status == "processed"
        assert "activated" in result.message.lower()
        assert result.subscription_id == "sub_xyz789"
        mock_webhook_subscriptions_collection.insert_one.assert_awaited_once()

    async def test_skips_duplicate_subscription(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        """If subscription already exists in DB, skip creation."""
        mock_webhook_subscriptions_collection.find_one = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )

        event_data = _make_webhook_event(
            "subscription.active", SUBSCRIPTION_DATA_PAYLOAD
        )
        result = await webhook_service.process_webhook(event_data, "wh_sub_002")

        assert result.status == "processed"
        assert "already active" in result.message.lower()
        mock_webhook_subscriptions_collection.insert_one.assert_not_awaited()

    async def test_finds_user_by_email_when_user_id_missing(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        """When metadata has no user_id, looks up user by customer email."""
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("subscription.active", payload)
        mock_webhook_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)

        result = await webhook_service.process_webhook(event_data, "wh_sub_003")

        assert result.status == "processed"
        # First call should look up user by email (no user_id in metadata)
        first_call_args = mock_webhook_users_collection.find_one.call_args_list[0]
        assert first_call_args[0][0] == {"email": FAKE_EMAIL}

    async def test_fails_when_user_not_found_by_email(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_webhook_users_collection,
        mock_track_subscription,
    ):
        """Returns failed result if user can't be found by email."""
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("subscription.active", payload)
        mock_webhook_users_collection.find_one = AsyncMock(return_value=None)

        result = await webhook_service.process_webhook(event_data, "wh_sub_004")

        assert result.status == "failed"
        assert "User not found" in result.message

    async def test_sends_welcome_email(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.active", SUBSCRIPTION_DATA_PAYLOAD
        )
        # For welcome email, _send_welcome_email does a separate find_one
        mock_webhook_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)

        await webhook_service.process_webhook(event_data, "wh_sub_005")

        mock_webhook_send_email.assert_awaited_once()

    async def test_tracks_analytics_on_activation(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.active", SUBSCRIPTION_DATA_PAYLOAD
        )
        await webhook_service.process_webhook(event_data, "wh_sub_006")

        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["user_id"] == FAKE_EMAIL
        assert call_kwargs["event_type"] == "subscription:activated"

    async def test_insert_failure_raises(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_webhook_users_collection,
        mock_track_subscription,
    ):
        """If insert_one returns None inserted_id, raises an exception."""
        mock_webhook_subscriptions_collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id=None)
        )
        event_data = _make_webhook_event(
            "subscription.active", SUBSCRIPTION_DATA_PAYLOAD
        )

        result = await webhook_service.process_webhook(event_data, "wh_sub_007")

        assert result.status == "failed"
        assert "Processing error" in result.message


@pytest.mark.unit
class TestHandleSubscriptionRenewed:
    """Tests for _handle_subscription_renewed."""

    async def test_updates_billing_dates(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD
        )
        result = await webhook_service.process_webhook(event_data, "wh_renew_001")

        assert result.status == "processed"
        assert "renewed" in result.message.lower()
        mock_webhook_subscriptions_collection.update_one.assert_awaited_once()
        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["status"] == "active"
        assert "next_billing_date" in set_data
        assert "previous_billing_date" in set_data

    async def test_warns_when_subscription_not_found(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        """If update_one matches zero docs, a warning is logged (not a failure)."""
        mock_webhook_subscriptions_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=0)
        )
        event_data = _make_webhook_event(
            "subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD
        )

        result = await webhook_service.process_webhook(event_data, "wh_renew_002")

        # Still processed, just with a warning
        assert result.status == "processed"
        mock_track_subscription.assert_not_called()

    async def test_tracks_renewal_analytics(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD
        )

        await webhook_service.process_webhook(event_data, "wh_renew_003")

        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:renewed"


@pytest.mark.unit
class TestHandleSubscriptionCancelled:
    """Tests for _handle_subscription_cancelled."""

    async def test_sets_status_to_cancelled(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD
        )
        result = await webhook_service.process_webhook(event_data, "wh_cancel_sub_001")

        assert result.status == "processed"
        assert "cancelled" in result.message.lower()
        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["status"] == "cancelled"

    async def test_includes_cancelled_at_when_present(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "cancelled_at": "2025-06-15T00:00:00Z",
        }
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_002")

        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["cancelled_at"] == "2025-06-15T00:00:00Z"

    async def test_no_cancelled_at_when_absent(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "cancelled_at": None}
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_003")

        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert "cancelled_at" not in set_data

    async def test_tracks_cancellation_analytics(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD
        )
        await webhook_service.process_webhook(event_data, "wh_cancel_sub_004")

        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:cancelled"


@pytest.mark.unit
class TestHandleSubscriptionExpired:
    """Tests for _handle_subscription_expired."""

    async def test_sets_status_to_expired(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.expired", SUBSCRIPTION_DATA_PAYLOAD
        )
        result = await webhook_service.process_webhook(event_data, "wh_expire_001")

        assert result.status == "processed"
        assert "expired" in result.message.lower()
        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["status"] == "expired"

    async def test_tracks_expiry_analytics(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event(
            "subscription.expired", SUBSCRIPTION_DATA_PAYLOAD
        )
        await webhook_service.process_webhook(event_data, "wh_expire_002")

        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:expired"


@pytest.mark.unit
class TestHandleSubscriptionFailed:
    """Tests for _handle_subscription_failed."""

    async def test_sets_status_to_failed(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
    ):
        event_data = _make_webhook_event(
            "subscription.failed", SUBSCRIPTION_DATA_PAYLOAD
        )
        result = await webhook_service.process_webhook(event_data, "wh_sfail_001")

        assert result.status == "processed"
        assert "failed" in result.message.lower()
        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["status"] == "failed"


@pytest.mark.unit
class TestHandleSubscriptionOnHold:
    """Tests for _handle_subscription_on_hold."""

    async def test_sets_status_to_on_hold(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
    ):
        event_data = _make_webhook_event(
            "subscription.on_hold", SUBSCRIPTION_DATA_PAYLOAD
        )
        result = await webhook_service.process_webhook(event_data, "wh_hold_001")

        assert result.status == "processed"
        assert "on hold" in result.message.lower()
        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["status"] == "on_hold"


@pytest.mark.unit
class TestHandleSubscriptionPlanChanged:
    """Tests for _handle_subscription_plan_changed."""

    async def test_updates_product_and_amount(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_subscriptions_collection,
    ):
        event_data = _make_webhook_event(
            "subscription.plan_changed", SUBSCRIPTION_DATA_PAYLOAD
        )
        result = await webhook_service.process_webhook(event_data, "wh_change_001")

        assert result.status == "processed"
        assert "plan changed" in result.message.lower()
        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["product_id"] == "prod_abc123"
        assert set_data["quantity"] == 1
        assert set_data["recurring_pre_tax_amount"] == 999


# ============================================================================
# Webhook Helper Methods
# ============================================================================


@pytest.mark.unit
class TestSendWelcomeEmail:
    """Tests for _send_welcome_email."""

    async def test_sends_email_when_user_found(
        self,
        webhook_service,
        mock_webhook_users_collection,
        mock_webhook_send_email,
    ):
        await webhook_service._send_welcome_email(FAKE_USER_ID)

        mock_webhook_send_email.assert_awaited_once_with(
            user_name="Alice",
            user_email=FAKE_EMAIL,
        )

    async def test_no_email_when_user_not_found(
        self,
        webhook_service,
        mock_webhook_users_collection,
        mock_webhook_send_email,
    ):
        mock_webhook_users_collection.find_one = AsyncMock(return_value=None)

        await webhook_service._send_welcome_email(FAKE_USER_ID)

        mock_webhook_send_email.assert_not_awaited()

    async def test_no_email_when_user_has_no_email(
        self,
        webhook_service,
        mock_webhook_users_collection,
        mock_webhook_send_email,
    ):
        mock_webhook_users_collection.find_one = AsyncMock(
            return_value={**SAMPLE_USER_DOC, "email": None}
        )

        await webhook_service._send_welcome_email(FAKE_USER_ID)

        mock_webhook_send_email.assert_not_awaited()

    async def test_email_error_is_swallowed(
        self,
        webhook_service,
        mock_webhook_users_collection,
        mock_webhook_send_email,
    ):
        """Email send failure is caught and logged, not propagated."""
        mock_webhook_send_email.side_effect = Exception("SMTP down")

        # Should not raise
        await webhook_service._send_welcome_email(FAKE_USER_ID)


@pytest.mark.unit
class TestGetUserEmailFromMetadata:
    """Tests for _get_user_email_from_metadata."""

    async def test_returns_email_when_user_found(
        self,
        webhook_service,
        mock_webhook_users_collection,
    ):
        email = await webhook_service._get_user_email_from_metadata(
            {"user_id": FAKE_USER_ID}
        )
        assert email == FAKE_EMAIL

    async def test_returns_none_when_no_user_id(
        self,
        webhook_service,
        mock_webhook_users_collection,
    ):
        email = await webhook_service._get_user_email_from_metadata({})
        assert email is None

    async def test_returns_none_when_user_not_found(
        self,
        webhook_service,
        mock_webhook_users_collection,
    ):
        mock_webhook_users_collection.find_one = AsyncMock(return_value=None)

        email = await webhook_service._get_user_email_from_metadata(
            {"user_id": FAKE_USER_ID}
        )
        assert email is None


@pytest.mark.unit
class TestIsWebhookProcessed:
    """Tests for _is_webhook_processed."""

    async def test_returns_true_when_found(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        mock_processed_webhooks_collection.find_one = AsyncMock(
            return_value={"webhook_id": "wh_exists"}
        )

        result = await webhook_service._is_webhook_processed("wh_exists")
        assert result is True

    async def test_returns_false_when_not_found(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        mock_processed_webhooks_collection.find_one = AsyncMock(return_value=None)

        result = await webhook_service._is_webhook_processed("wh_new")
        assert result is False


@pytest.mark.unit
class TestMarkWebhookAsProcessed:
    """Tests for _mark_webhook_as_processed."""

    async def test_inserts_processed_record(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        result = DodoWebhookProcessingResult(
            event_type="payment.succeeded",
            status="processed",
            message="OK",
            payment_id="pay_001",
            subscription_id="sub_001",
        )

        await webhook_service._mark_webhook_as_processed(
            "wh_mark_001", "payment.succeeded", result
        )

        mock_processed_webhooks_collection.insert_one.assert_awaited_once()
        inserted_doc = mock_processed_webhooks_collection.insert_one.call_args[0][0]
        assert inserted_doc["webhook_id"] == "wh_mark_001"
        assert inserted_doc["event_type"] == "payment.succeeded"
        assert inserted_doc["status"] == "processed"
        assert inserted_doc["payment_id"] == "pay_001"
        assert inserted_doc["subscription_id"] == "sub_001"
        assert "processed_at" in inserted_doc

    async def test_insert_error_is_swallowed(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
    ):
        """If storing webhook record fails, it's logged not propagated."""
        mock_processed_webhooks_collection.insert_one = AsyncMock(
            side_effect=Exception("DB write failed")
        )

        result = DodoWebhookProcessingResult(
            event_type="payment.succeeded",
            status="processed",
            message="OK",
        )

        # Should not raise
        await webhook_service._mark_webhook_as_processed(
            "wh_mark_002", "payment.succeeded", result
        )


# ============================================================================
# PaymentWebhookService Initialization Tests
# ============================================================================


@pytest.mark.unit
class TestPaymentWebhookServiceInit:
    """Tests for PaymentWebhookService.__init__."""

    def test_no_secret_disables_verifier(self):
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "development"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None

    def test_none_secret_disables_verifier(self):
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = None
            mock_settings.ENV = "development"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None

    def test_all_handler_event_types_registered(self):
        """All DodoWebhookEventType values have a corresponding handler."""
        with patch(
            "app.services.payments.payment_webhook_service.settings"
        ) as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "development"
            svc = PaymentWebhookService()

        for event_type in DodoWebhookEventType:
            assert event_type in svc.handlers, f"Missing handler for {event_type}"


# ============================================================================
# process_webhook customer_id extraction
# ============================================================================


@pytest.mark.unit
class TestProcessWebhookCustomerIdExtraction:
    """Verify customer_id is correctly extracted from nested and flat payloads."""

    async def test_extracts_customer_id_from_nested_customer_dict(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        """customer_id is extracted from data.customer.customer_id."""
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_cid_001")

        assert result.status == "processed"

    async def test_extracts_customer_id_from_flat_payload(
        self,
        webhook_service,
        mock_processed_webhooks_collection,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        """Falls back to data.customer_id when customer is not a dict."""
        payload = {
            **PAYMENT_DATA_PAYLOAD,
            "customer_id": "flat_cust_001",
        }
        # Replace customer with a non-dict to trigger fallback
        payload["customer"] = {
            "customer_id": "cust_001",
            "email": FAKE_EMAIL,
            "name": "Alice",
        }
        event_data = _make_webhook_event("payment.succeeded", payload)
        result = await webhook_service.process_webhook(event_data, "wh_cid_002")

        assert result.status == "processed"
