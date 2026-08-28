"""
Unit tests for DodoPaymentService and PaymentWebhookService.

Covers:
- DodoPaymentService: get_plans, create_subscription, verify_payment_completion,
  get_user_subscription_status
- PaymentWebhookService: verify_webhook_signature, process_webhook (all event types),
  idempotency, error paths, welcome email dispatch
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.constants.cache import UPGRADE_LINK_CACHE_TTL
from app.constants.payments import PAYMENT_HISTORY_LIMIT
from app.models.payment_models import (
    CreateSubscriptionResponse,
    PlanDocument,
    PlanDuration,
    PlanResponse,
    PlanType,
    ProCheckout,
    SubscriptionDocument,
    SubscriptionStatus,
    UserSubscriptionStatus,
)
from app.models.user_models import UserDocument
from app.models.webhook_models import (
    DodoWebhookEventType,
    DodoWebhookProcessingResult,
)
from app.services.payments.payment_service import DodoPaymentService
from app.services.payments.payment_webhook_service import PaymentWebhookService
from shared.py.wide_events import log

# ---------------------------------------------------------------------------
# Shared helpers / constants
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_EMAIL = "alice@example.com"
NOW = datetime.now(UTC)

SAMPLE_PLAN_DOC: dict[str, Any] = {
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

SAMPLE_PLAN = PlanDocument(
    id=str(SAMPLE_PLAN_DOC["_id"]),
    dodo_product_id="prod_abc123",
    name="Pro Monthly",
    description="Pro features billed monthly",
    amount=999,
    currency="USD",
    duration="monthly",
    max_users=5,
    features=["feature_a", "feature_b"],
    is_active=True,
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_SUBSCRIPTION_DOC: dict[str, Any] = {
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

SAMPLE_SUBSCRIPTION = SubscriptionDocument(
    id=str(SAMPLE_SUBSCRIPTION_DOC["_id"]),
    dodo_subscription_id="sub_xyz789",
    user_id=FAKE_USER_ID,
    product_id="prod_abc123",
    status="active",
    created_at=NOW,
    updated_at=NOW,
    quantity=1,
    currency="USD",
    recurring_pre_tax_amount=999,
)

SAMPLE_USER_DOC: dict[str, Any] = {
    "_id": ObjectId(FAKE_USER_ID),
    "email": FAKE_EMAIL,
    "first_name": "Alice",
    "name": "Alice Smith",
}


def _user(doc: dict[str, Any] | None) -> UserDocument | None:
    """Build the UserDocument the repository would return from a raw user dict."""
    if doc is None:
        return None
    data = dict(doc)
    _id = data.pop("_id", None)
    if _id is not None:
        data["id"] = str(_id)
    return UserDocument.model_validate(data)


def _set_user(mock_repo, doc: dict[str, Any] | None) -> None:
    val = _user(doc)
    mock_repo.get = AsyncMock(return_value=val)
    mock_repo.get_by_email = AsyncMock(return_value=val)


# Full webhook payloads -------------------------------------------------------

PAYMENT_DATA_PAYLOAD: dict[str, Any] = {
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

SUBSCRIPTION_DATA_PAYLOAD: dict[str, Any] = {
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


def _make_webhook_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
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
def mock_plan_repository():
    with patch("app.services.payments.payment_service.plan_repository") as mock_repo:
        mock_repo.list_plans = AsyncMock(return_value=[])
        yield mock_repo


@pytest.fixture
def mock_subscription_repository():
    with patch("app.services.payments.payment_service.subscription_repository") as mock_repo:
        mock_repo.get_active_for_user = AsyncMock(return_value=None)
        mock_repo.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_repo.get_user_id_by_dodo_id = AsyncMock(return_value=None)
        mock_repo.apply_update_by_dodo_id = AsyncMock(return_value=True)
        yield mock_repo


@pytest.fixture
def mock_users_collection():
    with patch("app.services.payments.payment_service.user_repository") as mock_repo:
        _set_user(mock_repo, SAMPLE_USER_DOC)
        yield mock_repo


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
def mock_webhook_subscription_repository():
    with patch(
        "app.services.payments.payment_webhook_service.subscription_repository"
    ) as mock_repo:
        mock_repo.get_by_dodo_id = AsyncMock(return_value=None)
        mock_repo.get_user_id_by_dodo_id = AsyncMock(return_value=FAKE_USER_ID)
        mock_repo.create = AsyncMock()
        mock_repo.apply_update_by_dodo_id = AsyncMock(return_value=True)
        yield mock_repo


@pytest.fixture
def mock_webhook_users_collection():
    with patch("app.services.payments.payment_webhook_service.user_repository") as mock_repo:
        _set_user(mock_repo, SAMPLE_USER_DOC)
        yield mock_repo


@pytest.fixture
def mock_processed_webhook_repository():
    with patch(
        "app.services.payments.payment_webhook_service.processed_webhook_repository"
    ) as mock_repo:
        mock_repo.is_processed = AsyncMock(return_value=False)
        mock_repo.mark_processed = AsyncMock()
        yield mock_repo


@pytest.fixture
def mock_track_payment():
    with patch("app.services.payments.payment_webhook_service.track_payment_event") as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_track_subscription():
    with patch("app.services.payments.payment_webhook_service.track_subscription_event") as mock_fn:
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
    with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
        mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
        mock_settings.ENV = "development"
        with patch("app.services.payments.payment_webhook_service.Webhook") as mock_wh_cls:
            mock_verifier = MagicMock()
            mock_wh_cls.return_value = mock_verifier
            svc = PaymentWebhookService()
    return svc


@pytest.fixture(autouse=True)
def mock_payment_service_invalidation():
    """Prevent payment_service.invalidate_plan_cache_by_dodo_id from hitting the DB.

    process_webhook now calls this after each successful handler to bust the
    subscription-plan cache.  Patch the module-level singleton so every webhook
    test stays fully in-memory.
    """
    with patch("app.services.payments.payment_webhook_service.payment_service") as mock_svc:
        mock_svc.invalidate_plan_cache_by_dodo_id = AsyncMock()
        yield mock_svc


# ============================================================================
# DodoPaymentService Tests
# ============================================================================


class TestGetPlans:
    """Tests for DodoPaymentService.get_plans."""

    async def test_returns_plans_from_database(
        self,
        payment_service,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """Fetches plans from DB when cache is empty."""
        mock_plan_repository.list_plans = AsyncMock(return_value=[SAMPLE_PLAN])

        plans = await payment_service.get_plans(active_only=True)

        assert len(plans) == 1
        assert plans[0].name == "Pro Monthly"
        assert plans[0].dodo_product_id == "prod_abc123"
        mock_plan_repository.list_plans.assert_awaited_once_with(active_only=True)
        mock_redis_cache.set.assert_awaited_once()

    async def test_returns_all_plans_when_active_only_false(
        self,
        payment_service,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """Passes empty query when active_only=False."""
        mock_plan_repository.list_plans = AsyncMock(return_value=[SAMPLE_PLAN])

        await payment_service.get_plans(active_only=False)

        mock_plan_repository.list_plans.assert_awaited_once_with(active_only=False)

    async def test_returns_plans_from_cache(
        self,
        payment_service,
        mock_plan_repository,
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
        mock_plan_repository.list_plans.assert_not_awaited()

    async def test_clears_cache_on_incompatible_data(
        self,
        payment_service,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """If cached data cannot be parsed, cache is cleared and DB is queried."""
        mock_redis_cache.get = AsyncMock(return_value=[{"bad_key": "bad_val"}])
        mock_plan_repository.list_plans = AsyncMock(return_value=[SAMPLE_PLAN])

        plans = await payment_service.get_plans()

        mock_redis_cache.delete.assert_awaited_once()
        assert len(plans) == 1

    async def test_adds_missing_dodo_product_id_from_cache(
        self,
        payment_service,
        mock_plan_repository,
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
        mock_plan_repository,
        mock_redis_cache,
    ):
        """Returns empty list when DB has no matching plans."""
        mock_plan_repository.list_plans = AsyncMock(return_value=[])

        plans = await payment_service.get_plans()

        assert plans == []

    async def test_plan_without_optional_fields(
        self,
        payment_service,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """Plans missing optional fields (description, max_users) still parse."""
        minimal_plan = PlanDocument(
            id=str(ObjectId()),
            name="Basic",
            amount=0,
            currency="USD",
            duration="monthly",
            is_active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        mock_plan_repository.list_plans = AsyncMock(return_value=[minimal_plan])

        plans = await payment_service.get_plans()

        assert plans[0].dodo_product_id == ""
        assert plans[0].description is None
        assert plans[0].max_users is None
        assert plans[0].features == []


class TestCreateSubscription:
    """Tests for DodoPaymentService.create_subscription."""

    async def test_success_returns_payment_link(
        self,
        payment_service,
        mock_users_collection,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Happy path: returns checkout URL when user exists and has no active sub."""
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_001"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_001"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=checkout_response)

        # Stub get_plans so plan name lookup doesn't fail
        mock_plan_repository.list_plans = AsyncMock(return_value=[])

        result = await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        assert result.subscription_id == "sess_001"
        assert result.payment_link == "https://checkout.dodo.dev/sess_001"
        assert result.status == "payment_link_created"

    async def test_raises_404_if_user_not_found(
        self,
        payment_service,
        mock_users_collection,
        mock_subscription_repository,
    ):
        _set_user(mock_users_collection, None)

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
        mock_subscription_repository,
    ):
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
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
        mock_subscription_repository,
        mock_dodo_client,
    ):
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
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
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """When a discount_code is provided, it appears in the params."""
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_002"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_002"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=checkout_response)

        mock_plan_repository.list_plans = AsyncMock(return_value=[])

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
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """When discount_code is None, it should NOT appear in params."""
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_003"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_003"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=checkout_response)

        mock_plan_repository.list_plans = AsyncMock(return_value=[])

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
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Verifies plan name lookup succeeds when a matching plan exists."""
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_004"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_004"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=checkout_response)

        mock_plan_repository.list_plans = AsyncMock(return_value=[SAMPLE_PLAN])

        result = await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        # Just verify it doesn't raise and returns the link
        assert result.status == "payment_link_created"

    async def test_custom_quantity_passed_to_checkout(
        self,
        payment_service,
        mock_users_collection,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Verifies custom quantity ends up in the product_cart."""
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_005"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_005"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=checkout_response)

        mock_plan_repository.list_plans = AsyncMock(return_value=[])

        await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
            quantity=3,
        )

        call_kwargs = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert call_kwargs["product_cart"][0]["quantity"] == 3


@pytest.mark.unit
class TestCancelSubscription:
    """Tests for DodoPaymentService.cancel_subscription."""

    async def test_cancels_at_next_billing_date(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_user_id_by_dodo_id = AsyncMock(return_value=FAKE_USER_ID)

        updated = MagicMock()
        updated.status = "active"
        updated.cancelled_at = None
        updated.next_billing_date = None
        mock_dodo_client.subscriptions = MagicMock()
        mock_dodo_client.subscriptions.update = MagicMock(return_value=updated)

        result = await payment_service.cancel_subscription(FAKE_USER_ID)

        mock_dodo_client.subscriptions.update.assert_called_once_with(
            "sub_xyz789",
            cancel_at_next_billing_date=True,
        )
        # The local row is mirrored with the flag set and status kept.
        update_call = mock_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["cancel_at_next_billing_date"] is True
        assert set_data["status"] == "active"
        assert "cancelled_at" not in set_data
        assert isinstance(result, UserSubscriptionStatus)

    async def test_cancels_with_cancelled_at(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_user_id_by_dodo_id = AsyncMock(return_value=FAKE_USER_ID)

        updated = MagicMock()
        updated.status = "active"
        updated.cancelled_at = datetime(2025, 6, 15, tzinfo=UTC)
        updated.next_billing_date = None
        mock_dodo_client.subscriptions = MagicMock()
        mock_dodo_client.subscriptions.update = MagicMock(return_value=updated)

        await payment_service.cancel_subscription(FAKE_USER_ID)

        update_call = mock_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["cancelled_at"] == "2025-06-15T00:00:00+00:00"

    async def test_raises_404_without_active_subscription(
        self,
        payment_service,
        mock_subscription_repository,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await payment_service.cancel_subscription(FAKE_USER_ID)

        assert exc_info.value.status_code == 404

    async def test_raises_502_on_dodo_error(
        self,
        payment_service,
        mock_subscription_repository,
        mock_dodo_client,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_dodo_client.subscriptions = MagicMock()
        mock_dodo_client.subscriptions.update = MagicMock(side_effect=Exception("Dodo API down"))

        with pytest.raises(HTTPException) as exc_info:
            await payment_service.cancel_subscription(FAKE_USER_ID)

        assert exc_info.value.status_code == 502
        assert "Payment service error" in str(exc_info.value.detail)


@pytest.mark.unit
class TestVerifyPaymentCompletion:
    """Tests for DodoPaymentService.verify_payment_completion."""

    async def test_active_subscription_returns_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_users_collection,
        mock_send_email,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        _set_user(mock_users_collection, SAMPLE_USER_DOC)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is True
        assert result.subscription_id == "sub_xyz789"
        mock_send_email.assert_awaited_once()

    async def test_no_subscription_returns_not_completed(
        self,
        payment_service,
        mock_subscription_repository,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False
        assert "No active subscription" in result.message

    async def test_email_failure_does_not_raise(
        self,
        payment_service,
        mock_subscription_repository,
        mock_users_collection,
        mock_send_email,
    ):
        """Email failure is swallowed silently."""
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_send_email.side_effect = Exception("SMTP error")

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is True

    async def test_no_email_on_user_without_email(
        self,
        payment_service,
        mock_subscription_repository,
        mock_users_collection,
        mock_send_email,
    ):
        """No email sent when user has no email address."""
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        user_without_email = {**SAMPLE_USER_DOC, "email": None}
        _set_user(mock_users_collection, user_without_email)

        await payment_service.verify_payment_completion(FAKE_USER_ID)

        mock_send_email.assert_not_awaited()

    async def test_no_email_when_user_not_found(
        self,
        payment_service,
        mock_subscription_repository,
        mock_users_collection,
        mock_send_email,
    ):
        """No email sent when user doesn't exist in DB."""
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        _set_user(mock_users_collection, None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is True
        mock_send_email.assert_not_awaited()


class TestGetUserSubscriptionStatus:
    """Tests for DodoPaymentService.get_user_subscription_status."""

    async def test_no_subscription_returns_free_status(
        self,
        payment_service,
        mock_subscription_repository,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

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
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_plan_repository.list_plans = AsyncMock(return_value=[SAMPLE_PLAN])

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.plan_type == PlanType.PRO
        assert status.status == SubscriptionStatus.ACTIVE
        assert status.has_subscription is True
        assert status.can_upgrade is True
        assert status.can_downgrade is True
        assert status.current_plan is not None
        assert status.subscription["dodo_subscription_id"] == "sub_xyz789"
        assert status.subscription["status"] == "active"

    async def test_active_subscription_no_matching_plan(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """When subscription product_id doesn't match any plan, current_plan is None."""
        sub_doc = SubscriptionDocument(
            id=str(SAMPLE_SUBSCRIPTION_DOC["_id"]),
            dodo_subscription_id="sub_xyz789",
            user_id=FAKE_USER_ID,
            product_id="prod_unknown",
            status="active",
            created_at=NOW,
            updated_at=NOW,
        )
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=sub_doc)
        mock_plan_repository.list_plans = AsyncMock(return_value=[SAMPLE_PLAN])

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.current_plan is None

    async def test_plan_lookup_error_sets_plan_to_none(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """If get_plans raises, plan gracefully falls back to None."""
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        # Make get_plans fail by causing the cache to raise
        mock_redis_cache.get = AsyncMock(side_effect=Exception("Redis down"))
        mock_plan_repository.list_plans = AsyncMock(side_effect=Exception("DB down"))

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.current_plan is None


# ============================================================================
# Pro checkout, payment history, and the agent-facing details view
# ============================================================================


def _plan(
    *,
    name: str,
    amount: int,
    duration: str,
    product_id: str,
    plan_id: str,
    active: bool = True,
) -> PlanDocument:
    return PlanDocument(
        id=plan_id,
        dodo_product_id=product_id,
        name=name,
        description=None,
        amount=amount,
        currency="USD",
        duration=duration,
        max_users=1,
        features=["Unlimited memories"],
        is_active=active,
        created_at=NOW,
        updated_at=NOW,
    )


# The shipped catalogue shape: Free and Enterprise are both priced at 0 with no
# Dodo product, so only the two Pro rows are actually purchasable.
CATALOGUE = [
    _plan(name="Free", amount=0, duration="monthly", product_id="", plan_id="p_free"),
    _plan(name="Pro", amount=3000, duration="monthly", product_id="prod_m", plan_id="p_m"),
    _plan(name="Pro", amount=30000, duration="yearly", product_id="prod_y", plan_id="p_y"),
    _plan(name="Enterprise", amount=0, duration="monthly", product_id="", plan_id="p_ent"),
]


def _payment_page(*payments):
    page = MagicMock()
    page.items = list(payments)
    return page


def _payment(payment_id: str, created_at: datetime, amount: int = 3000):
    payment = MagicMock()
    payment.payment_id = payment_id
    payment.status = "succeeded"
    payment.total_amount = amount
    payment.currency = "USD"
    payment.created_at = created_at
    payment.payment_method = "card"
    return payment


class TestPlanForSubscription:
    """Tests for DodoPaymentService._plan_for_subscription."""

    async def test_resolves_the_product_from_the_full_catalogue(
        self, payment_service, mock_plan_repository, mock_redis_cache
    ):
        """A cancelled subscription's plan is inactive in the catalogue but the
        row still resolves — the read is deliberately active_only=False."""
        sub = SubscriptionDocument(
            id="s1",
            dodo_subscription_id="sub_old",
            user_id=FAKE_USER_ID,
            product_id="prod_m",
            status="cancelled",
        )
        retired = _plan(
            name="Pro",
            amount=3000,
            duration="monthly",
            product_id="prod_m",
            plan_id="p_m",
            active=False,
        )
        mock_plan_repository.list_plans = AsyncMock(return_value=[retired])

        plan = await payment_service._plan_for_subscription(sub)

        assert plan is not None and plan.dodo_product_id == "prod_m"
        mock_plan_repository.list_plans.assert_awaited_once_with(active_only=False)

    async def test_a_catalogue_failure_degrades_with_a_full_warning(
        self, payment_service, mock_subscription_repository, mock_redis_cache
    ):
        log.reset()
        sub = SubscriptionDocument(
            id="s1",
            dodo_subscription_id="sub_x",
            user_id=FAKE_USER_ID,
            product_id="prod_m",
            status="active",
        )
        with patch.object(
            payment_service, "get_plans", AsyncMock(side_effect=RuntimeError("dodo down"))
        ):
            plan = await payment_service._plan_for_subscription(sub)

        assert plan is None
        assert log.get()["warnings"] == [
            {
                "msg": "[PAYMENT] Could not resolve the plan behind a subscription",
                "dodo_subscription_id": "sub_x",
                "failure_reason": "plan_resolution_failed",
                "error_type": "RuntimeError",
            }
        ]


class TestGetProPlan:
    """Tests for DodoPaymentService.get_pro_plan."""

    async def test_only_asks_the_catalogue_for_active_plans(
        self, payment_service, mock_plan_repository, mock_redis_cache
    ):
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)

        await payment_service.get_pro_plan(PlanDuration.MONTHLY)

        mock_plan_repository.list_plans.assert_awaited_once_with(active_only=True)

    async def test_a_one_cent_plan_is_still_purchasable(
        self, payment_service, mock_plan_repository, mock_redis_cache
    ):
        """Amount is minor units — the paid-tier check is >0, not a rounded
        threshold that would silently drop genuinely priced products."""
        cheap = _plan(
            name="Pro",
            amount=1,
            duration="monthly",
            product_id="prod_m",
            plan_id="p_m",
        )
        mock_plan_repository.list_plans = AsyncMock(return_value=[cheap])

        plan = await payment_service.get_pro_plan(PlanDuration.MONTHLY)

        assert plan.dodo_product_id == "prod_m"

    async def test_picks_the_paid_plan_for_the_requested_cycle(
        self, payment_service, mock_plan_repository, mock_redis_cache
    ):
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)

        monthly = await payment_service.get_pro_plan(PlanDuration.MONTHLY)
        yearly = await payment_service.get_pro_plan(PlanDuration.YEARLY)

        assert (monthly.dodo_product_id, monthly.amount) == ("prod_m", 3000)
        assert (yearly.dodo_product_id, yearly.amount) == ("prod_y", 30000)

    async def test_never_returns_free_or_enterprise(
        self, payment_service, mock_plan_repository, mock_redis_cache
    ):
        """Both are priced at 0 with no product id — selling either would 502 at Dodo."""
        free_and_enterprise = [CATALOGUE[0], CATALOGUE[3]]
        mock_plan_repository.list_plans = AsyncMock(return_value=free_and_enterprise)

        with pytest.raises(HTTPException) as exc:
            await payment_service.get_pro_plan(PlanDuration.MONTHLY)

        assert exc.value.status_code == 500

    async def test_a_zero_priced_product_is_not_treated_as_pro(
        self, payment_service, mock_plan_repository, mock_redis_cache
    ):
        """A free-trial product would be purchasable but is not the paid tier."""
        trial = _plan(
            name="Trial", amount=0, duration="monthly", product_id="prod_trial", plan_id="p_trial"
        )
        mock_plan_repository.list_plans = AsyncMock(return_value=[trial, CATALOGUE[1]])

        plan = await payment_service.get_pro_plan(PlanDuration.MONTHLY)

        assert plan.dodo_product_id == "prod_m"

    async def test_missing_cycle_fails_loudly(
        self, payment_service, mock_plan_repository, mock_redis_cache
    ):
        log.reset()
        mock_plan_repository.list_plans = AsyncMock(return_value=[CATALOGUE[1]])

        with pytest.raises(HTTPException) as exc:
            await payment_service.get_pro_plan(PlanDuration.YEARLY)

        assert exc.value.status_code == 500
        assert exc.value.detail == "No purchasable yearly plan is configured"
        assert log.get()["errors"] == [
            {
                "msg": "[PAYMENT] No purchasable plan in the catalogue",
                "billing_cycle": PlanDuration.YEARLY,
                "active_plans": 1,
            }
        ]


class TestCreateProCheckout:
    """Tests for DodoPaymentService.create_pro_checkout."""

    async def test_uses_the_exact_cache_key_and_mint_arguments(
        self,
        payment_service,
        mock_plan_repository,
        mock_subscription_repository,
        mock_users_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        session = MagicMock()
        session.session_id = "cs_1"
        session.checkout_url = "https://checkout.dodopayments.com/s/cs_1"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=session)

        mint = AsyncMock(
            return_value=CreateSubscriptionResponse(
                subscription_id="cs_1",
                payment_link="https://checkout.dodopayments.com/s/cs_1",
                status="payment_link_created",
            )
        )
        with patch.object(payment_service, "create_subscription", mint):
            await payment_service.create_pro_checkout(FAKE_USER_ID, PlanDuration.YEARLY)

        upgrade_gets = [
            call
            for call in mock_redis_cache.get.await_args_list
            if call.args[0] == f"upgrade_link:{FAKE_USER_ID}:yearly"
        ]
        assert len(upgrade_gets) == 1
        # The checkout session must be created for THIS user, tied by metadata.
        mint.assert_awaited_once_with(FAKE_USER_ID, "prod_y")

    async def test_caches_the_session_under_the_one_hour_ttl(
        self,
        payment_service,
        mock_plan_repository,
        mock_subscription_repository,
        mock_users_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        session = MagicMock()
        session.session_id = "cs_2"
        session.checkout_url = "https://checkout.dodopayments.com/s/cs_2"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=session)

        await payment_service.create_pro_checkout(FAKE_USER_ID)

        upgrade_calls = [
            call
            for call in mock_redis_cache.set.await_args_list
            if call.args[0] == f"upgrade_link:{FAKE_USER_ID}:monthly"
        ]
        assert len(upgrade_calls) == 1
        assert upgrade_calls[0].kwargs["ttl"] == UPGRADE_LINK_CACHE_TTL

    async def test_mints_a_session_for_the_resolved_pro_product(
        self,
        payment_service,
        mock_plan_repository,
        mock_subscription_repository,
        mock_users_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        session = MagicMock()
        session.session_id = "cs_1"
        session.checkout_url = "https://checkout.dodopayments.com/s/cs_1"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=session)

        pro = await payment_service.create_pro_checkout(FAKE_USER_ID, PlanDuration.YEARLY)

        assert pro.checkout.payment_link == "https://checkout.dodopayments.com/s/cs_1"
        assert pro.plan.dodo_product_id == "prod_y"
        cart = mock_dodo_client.checkout_sessions.create.call_args.kwargs["product_cart"]
        assert cart[0]["product_id"] == "prod_y"

    async def test_reuses_the_cached_session_instead_of_minting_another(
        self,
        payment_service,
        mock_plan_repository,
        mock_subscription_repository,
        mock_users_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """A user who hits limits repeatedly must not strand a session per hit."""
        cached = ProCheckout(
            plan=PlanResponse(
                id="plan_pro",
                dodo_product_id="prod_y",
                name="Pro",
                amount=30000,
                currency="USD",
                duration=PlanDuration.YEARLY,
                is_active=True,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            checkout=CreateSubscriptionResponse(
                subscription_id="cs_cached",
                payment_link="https://checkout.dodopayments.com/s/cs_cached",
                status="payment_link_created",
            ),
        )
        mock_redis_cache.get = AsyncMock(return_value=cached.model_dump())
        mock_dodo_client.checkout_sessions.create = MagicMock()

        pro = await payment_service.create_pro_checkout(FAKE_USER_ID)

        assert pro.checkout.payment_link == "https://checkout.dodopayments.com/s/cs_cached"
        # The price comes from the cached resolution, not a fresh catalogue read.
        assert pro.plan.amount == 30000
        mock_dodo_client.checkout_sessions.create.assert_not_called()

    async def test_caches_the_session_it_mints(
        self,
        payment_service,
        mock_plan_repository,
        mock_subscription_repository,
        mock_users_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        session = MagicMock()
        session.session_id = "cs_2"
        session.checkout_url = "https://checkout.dodopayments.com/s/cs_2"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=session)

        await payment_service.create_pro_checkout(FAKE_USER_ID)

        cached_keys = [call.args[0] for call in mock_redis_cache.set.await_args_list]
        upgrade_key = f"upgrade_link:{FAKE_USER_ID}:monthly"
        assert upgrade_key in cached_keys
        cached_payload = next(
            call.args[1]
            for call in mock_redis_cache.set.await_args_list
            if call.args[0] == upgrade_key
        )
        assert set(cached_payload) == {"plan", "checkout"}


class TestGetPaymentHistory:
    """Tests for DodoPaymentService.get_payment_history."""

    async def test_reads_this_users_ledger_at_the_requested_limit(
        self, payment_service, mock_subscription_repository, mock_dodo_client
    ):
        sub = SubscriptionDocument(
            id="s1", dodo_subscription_id="sub_1", user_id=FAKE_USER_ID, status="active"
        )
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[sub])
        mock_dodo_client.payments.list = MagicMock(return_value=_payment_page())

        await payment_service.get_payment_history(FAKE_USER_ID, limit=7)

        mock_subscription_repository.list_for_user.assert_awaited_once_with(FAKE_USER_ID)
        list_call = mock_dodo_client.payments.list.call_args
        assert list_call.kwargs["subscription_id"] == "sub_1"
        assert list_call.kwargs["page_size"] == 7

    async def test_carries_status_and_method_from_the_ledger(
        self, payment_service, mock_subscription_repository, mock_dodo_client
    ):
        sub = SubscriptionDocument(
            id="s1", dodo_subscription_id="sub_1", user_id=FAKE_USER_ID, status="active"
        )
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[sub])
        payment = _payment("pay_1", datetime(2026, 1, 1, tzinfo=UTC))
        payment.status = "partially_refunded"
        payment.payment_method = "paypal"
        mock_dodo_client.payments.list = MagicMock(return_value=_payment_page(payment))

        history = await payment_service.get_payment_history(FAKE_USER_ID)

        assert history[0].status == "partially_refunded"
        assert history[0].payment_method == "paypal"

    async def test_no_subscriptions_means_no_ledger_call(
        self, payment_service, mock_subscription_repository, mock_dodo_client
    ):
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[])
        mock_dodo_client.payments.list = MagicMock()

        assert await payment_service.get_payment_history(FAKE_USER_ID) == []
        mock_dodo_client.payments.list.assert_not_called()

    async def test_merges_every_subscription_newest_first(
        self, payment_service, mock_subscription_repository, mock_dodo_client
    ):
        """A cancelled subscription's charges still belong in the user's history."""
        old = SubscriptionDocument(
            id="s1", dodo_subscription_id="sub_old", user_id=FAKE_USER_ID, status="cancelled"
        )
        current = SubscriptionDocument(
            id="s2", dodo_subscription_id="sub_new", user_id=FAKE_USER_ID, status="active"
        )
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[current, old])
        pages = {
            "sub_old": _payment_page(_payment("pay_old", datetime(2025, 1, 1, tzinfo=UTC))),
            "sub_new": _payment_page(_payment("pay_new", datetime(2026, 1, 1, tzinfo=UTC))),
        }
        mock_dodo_client.payments.list = MagicMock(
            side_effect=lambda *, subscription_id, page_size: pages[subscription_id]
        )

        history = await payment_service.get_payment_history(FAKE_USER_ID)

        assert [entry.payment_id for entry in history] == ["pay_new", "pay_old"]
        assert history[0].amount == 3000

    async def test_caps_the_result_at_the_requested_limit(
        self, payment_service, mock_subscription_repository, mock_dodo_client
    ):
        sub = SubscriptionDocument(
            id="s1", dodo_subscription_id="sub_1", user_id=FAKE_USER_ID, status="active"
        )
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[sub])
        mock_dodo_client.payments.list = MagicMock(
            return_value=_payment_page(
                *(_payment(f"pay_{i}", datetime(2026, 1, i + 1, tzinfo=UTC)) for i in range(5))
            )
        )

        history = await payment_service.get_payment_history(FAKE_USER_ID, limit=2)

        assert len(history) == 2


class TestGetSubscriptionDetails:
    """Tests for DodoPaymentService.get_subscription_details."""

    async def test_free_user_reports_free_and_reads_no_ledger(
        self, payment_service, mock_subscription_repository, mock_dodo_client
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[])
        mock_dodo_client.payments.list = MagicMock()

        details = await payment_service.get_subscription_details(FAKE_USER_ID)

        assert details.plan_type == PlanType.FREE
        assert details.is_subscribed is False
        assert details.payments == []
        mock_subscription_repository.get_active_for_user.assert_awaited_once_with(FAKE_USER_ID)
        mock_dodo_client.payments.list.assert_not_called()

    async def test_the_ledger_read_scopes_to_this_user_at_the_default_limit(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Both the free and the pro path must read the ledger for the RIGHT
        user, at the shipped history limit — not an unbounded page."""
        subscription = SubscriptionDocument(
            id="s1",
            dodo_subscription_id="sub_1",
            user_id=FAKE_USER_ID,
            product_id="prod_m",
            status="active",
        )
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=subscription)
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[subscription])
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        mock_dodo_client.payments.list = MagicMock(return_value=_payment_page())

        await payment_service.get_subscription_details(FAKE_USER_ID, history_limit=3)

        list_call = mock_dodo_client.payments.list.call_args
        assert list_call.kwargs["page_size"] == 3
        assert PAYMENT_HISTORY_LIMIT == 10  # the default the free path must use
        mock_subscription_repository.list_for_user.assert_awaited_once_with(FAKE_USER_ID)

    async def test_a_former_subscriber_still_sees_their_charges(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Cancelled-and-gone must not mean history-wiped: the ledger read runs on
        every subscription ever held, active or not."""
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        cancelled = SubscriptionDocument(
            id="s1",
            dodo_subscription_id="sub_old",
            user_id=FAKE_USER_ID,
            product_id="prod_m",
            status="cancelled",
        )
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[cancelled])
        mock_dodo_client.payments.list = MagicMock(
            return_value=_payment_page(_payment("pay_old", datetime(2025, 6, 1, tzinfo=UTC)))
        )

        details = await payment_service.get_subscription_details(FAKE_USER_ID, history_limit=4)

        assert details.plan_type == PlanType.FREE
        assert details.is_subscribed is False
        assert [entry.payment_id for entry in details.payments] == ["pay_old"]
        mock_subscription_repository.list_for_user.assert_awaited_once_with(FAKE_USER_ID)
        list_call = mock_dodo_client.payments.list.call_args
        assert list_call.kwargs["subscription_id"] == "sub_old"
        assert list_call.kwargs["page_size"] == 4

    async def test_pro_user_carries_plan_price_renewal_and_charges(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        subscription = SubscriptionDocument(
            id="s1",
            dodo_subscription_id="sub_1",
            user_id=FAKE_USER_ID,
            product_id="prod_m",
            status="active",
            next_billing_date="2026-04-14T12:00:00Z",
            cancel_at_next_billing_date=True,
        )
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=subscription)
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[subscription])
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        mock_dodo_client.payments.list = MagicMock(
            return_value=_payment_page(_payment("pay_1", datetime(2026, 3, 14, tzinfo=UTC)))
        )

        details = await payment_service.get_subscription_details(FAKE_USER_ID)

        assert details.plan_type == PlanType.PRO
        assert details.is_subscribed is True
        assert details.status == SubscriptionStatus.ACTIVE
        assert details.plan_name == "Pro"
        assert (details.amount, details.currency) == (3000, "USD")
        assert details.billing_cycle == PlanDuration.MONTHLY
        assert details.next_billing_date == "2026-04-14T12:00:00Z"
        assert details.cancel_at_next_billing_date is True
        assert [entry.payment_id for entry in details.payments] == ["pay_1"]

    async def test_unresolvable_plan_still_reports_the_user_as_pro(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """The subscription row is authoritative; the catalogue is decoration on top."""
        subscription = SubscriptionDocument(
            id="s1",
            dodo_subscription_id="sub_1",
            user_id=FAKE_USER_ID,
            product_id="prod_m",
            status="active",
        )
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=subscription)
        mock_subscription_repository.list_for_user = AsyncMock(return_value=[subscription])
        mock_redis_cache.get = AsyncMock(side_effect=Exception("Redis down"))
        mock_plan_repository.list_plans = AsyncMock(side_effect=Exception("DB down"))
        mock_dodo_client.payments.list = MagicMock(return_value=_payment_page())

        details = await payment_service.get_subscription_details(FAKE_USER_ID)

        assert details.plan_type == PlanType.PRO
        assert details.is_subscribed is True
        assert details.plan_name is None


# ============================================================================
# DodoPaymentService Initialization Tests
# ============================================================================


class TestDodoPaymentServiceInit:
    """Tests for DodoPaymentService.__init__."""

    def test_production_env_uses_live_mode(self):
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "production"
            mock_settings.DODO_PAYMENTS_API_KEY = "sk_live_test"
            mock_settings.DODO_PAYMENTS_BASE_URL = None
            with patch("app.services.payments.payment_service.DodoPayments") as mock_cls:
                DodoPaymentService()
                mock_cls.assert_called_once_with(
                    bearer_token="sk_live_test",
                    environment="live_mode",
                )

    def test_development_env_uses_test_mode(self):
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "development"
            mock_settings.DODO_PAYMENTS_API_KEY = "sk_test_test"
            mock_settings.DODO_PAYMENTS_BASE_URL = None
            with patch("app.services.payments.payment_service.DodoPayments") as mock_cls:
                DodoPaymentService()
                mock_cls.assert_called_once_with(
                    bearer_token="sk_test_test",
                    environment="test_mode",
                )

    def test_base_url_override_wins_over_environment(self):
        """When DODO_PAYMENTS_BASE_URL is set, it points the SDK at that URL
        instead of the real environment endpoint."""
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "development"
            mock_settings.DODO_PAYMENTS_API_KEY = "sk_test_test"
            mock_settings.DODO_PAYMENTS_BASE_URL = "http://localhost:8899"
            with patch("app.services.payments.payment_service.DodoPayments") as mock_cls:
                DodoPaymentService()
                mock_cls.assert_called_once_with(
                    bearer_token="sk_test_test",
                    base_url="http://localhost:8899",
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
                with patch("app.services.payments.payment_service.log") as mock_log:
                    # Should not raise
                    svc = DodoPaymentService()

                # Init failure leaves the service without a usable client
                assert not hasattr(svc, "client")
                # The failure must be surfaced in the logs, not swallowed
                mock_log.error.assert_called_once()


# ============================================================================
# PaymentWebhookService Tests
# ============================================================================


class TestVerifyWebhookSignature:
    """Tests for PaymentWebhookService.verify_webhook_signature."""

    def test_returns_false_when_no_verifier_configured(self) -> None:
        """When no verifier is configured, fail closed and reject the webhook."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "production"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None
        result = svc.verify_webhook_signature("{}", {})
        assert result is False

    def test_production_valid_signature(self):
        """In production with valid signature, returns True."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch("app.services.payments.payment_webhook_service.Webhook") as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(return_value=None)
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
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
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch("app.services.payments.payment_webhook_service.Webhook") as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(side_effect=Exception("Invalid signature"))
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
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
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch("app.services.payments.payment_webhook_service.Webhook") as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(return_value=None)
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
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
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "bad_secret"
            mock_settings.ENV = "production"
            with patch(
                "app.services.payments.payment_webhook_service.Webhook",
                side_effect=Exception("Bad secret format"),
            ):
                svc = PaymentWebhookService()

        assert svc.webhook_verifier is None


class TestProcessWebhookIdempotency:
    """Tests for idempotency / deduplication in process_webhook."""

    async def test_already_processed_webhook_is_skipped(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        """If webhook_id was already processed, returns 'ignored' immediately."""
        mock_processed_webhook_repository.is_processed = AsyncMock(
            return_value={"webhook_id": "wh_dup"}
        )

        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_dup")

        assert result.status == "ignored"
        assert "already processed" in result.message

    async def test_unknown_event_type_is_ignored_and_recorded(
        self,
        webhook_service,
        mock_processed_webhook_repository,
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
        mock_processed_webhook_repository.mark_processed.assert_awaited()
        webhook_service.handlers = original_handlers

    async def test_processing_failure_returns_failed_result(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        """When event parsing fails, returns a 'failed' result."""
        bad_data = {"type": "INVALID_TYPE", "data": {}}

        result = await webhook_service.process_webhook(bad_data, "wh_bad")

        assert result.status == "failed"
        assert "Processing error" in result.message


# ============================================================================
# Payment Event Handlers
# ============================================================================


class TestHandlePaymentSucceeded:
    """Tests for _handle_payment_succeeded via process_webhook."""

    async def test_processes_valid_payment_success(
        self,
        webhook_service,
        mock_processed_webhook_repository,
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
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_pay_002")

        mock_track_payment.assert_called_once()
        call_kwargs = mock_track_payment.call_args[1]
        assert call_kwargs["user_id"] == FAKE_USER_ID
        assert call_kwargs["payment_id"] == "pay_001"

    async def test_analytics_uses_metadata_user_id_without_db_lookup(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        """The metadata user id is the PostHog distinct id — no user lookup."""
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {"user_id": "unresolved-user-id"}}
        event_data = _make_webhook_event("payment.succeeded", payload)

        await webhook_service.process_webhook(event_data, "wh_pay_003")

        mock_track_payment.assert_called_once()
        assert mock_track_payment.call_args[1]["user_id"] == "unresolved-user-id"

    async def test_no_analytics_when_no_user_id_in_metadata(
        self,
        webhook_service,
        mock_processed_webhook_repository,
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
        mock_processed_webhook_repository,
    ):
        """When payment data can't be parsed, ValueError is raised (caught by process_webhook)."""
        bad_payload = {"incomplete": True}
        event_data = _make_webhook_event("payment.succeeded", bad_payload)

        result = await webhook_service.process_webhook(event_data, "wh_pay_bad")

        assert result.status == "failed"
        assert "Processing error" in result.message


class TestHandlePaymentFailed:
    """Tests for _handle_payment_failed."""

    async def test_processes_payment_failure(
        self,
        webhook_service,
        mock_processed_webhook_repository,
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
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.failed", PAYMENT_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_fail_002")

        mock_track_payment.assert_called_once()
        call_kwargs = mock_track_payment.call_args[1]
        assert call_kwargs["event_type"] == "payment:failed"


class TestHandlePaymentProcessing:
    """Tests for _handle_payment_processing."""

    async def test_processes_payment_processing_event(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        event_data = _make_webhook_event("payment.processing", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_proc_001")

        assert result.status == "processed"
        assert "processing" in result.message.lower()


class TestHandlePaymentCancelled:
    """Tests for _handle_payment_cancelled."""

    async def test_processes_payment_cancellation(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        event_data = _make_webhook_event("payment.cancelled", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_cancel_001")

        assert result.status == "processed"
        assert "cancellation" in result.message.lower()


# ============================================================================
# Subscription Event Handlers
# ============================================================================


class TestHandleSubscriptionActive:
    """Tests for _handle_subscription_active."""

    async def test_creates_subscription_record(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_sub_001")

        assert result.status == "processed"
        assert "activated" in result.message.lower()
        assert result.subscription_id == "sub_xyz789"
        mock_webhook_subscription_repository.create.assert_awaited_once()

    async def test_skips_duplicate_subscription(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        """If subscription already exists in DB, skip creation."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION_DOC
        )

        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_sub_002")

        assert result.status == "processed"
        assert "already active" in result.message.lower()
        mock_webhook_subscription_repository.create.assert_not_awaited()

    async def test_finds_user_by_email_when_user_id_missing(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        """When metadata has no user_id, looks up user by customer email."""
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("subscription.active", payload)
        _set_user(mock_webhook_users_collection, SAMPLE_USER_DOC)

        result = await webhook_service.process_webhook(event_data, "wh_sub_003")

        assert result.status == "processed"
        # No user_id in metadata → user is looked up by email through the repo.
        mock_webhook_users_collection.get_by_email.assert_awaited_with(FAKE_EMAIL)

    async def test_fails_when_user_not_found_by_email(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_track_subscription,
    ):
        """Returns failed result if user can't be found by email."""
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("subscription.active", payload)
        _set_user(mock_webhook_users_collection, None)

        result = await webhook_service.process_webhook(event_data, "wh_sub_004")

        assert result.status == "failed"
        assert "User not found" in result.message

    async def test_sends_welcome_email(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        # For welcome email, _send_welcome_email does a separate find_one
        _set_user(mock_webhook_users_collection, SAMPLE_USER_DOC)

        await webhook_service.process_webhook(event_data, "wh_sub_005")

        mock_webhook_send_email.assert_awaited_once()

    async def test_tracks_analytics_on_activation(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_sub_006")

        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["user_id"] == FAKE_USER_ID
        assert call_kwargs["event_type"] == "subscription:activated"

    async def test_insert_failure_raises(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_track_subscription,
    ):
        """If the repository create fails, the webhook returns a failed result."""
        mock_webhook_subscription_repository.create = AsyncMock(
            side_effect=Exception("insert failed")
        )
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event_data, "wh_sub_007")

        assert result.status == "failed"
        assert "Processing error" in result.message


class TestHandleSubscriptionRenewed:
    """Tests for _handle_subscription_renewed."""

    async def test_updates_billing_dates(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_renew_001")

        assert result.status == "processed"
        assert "renewed" in result.message.lower()
        mock_webhook_subscription_repository.apply_update_by_dodo_id.assert_awaited_once()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "active"
        assert "next_billing_date" in set_data
        assert "previous_billing_date" in set_data

    async def test_omitted_billing_dates_are_not_written_as_null(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        """A renewal that omits the billing dates must leave the stored ones alone.

        Passing them to SubscriptionUpdate marks them in model_fields_set even
        when None, so the repository's model_dump(exclude_unset=True) emits
        ``next_billing_date: None`` and the $set overwrites good stored values
        with null.
        """
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "next_billing_date": None,
            "previous_billing_date": None,
        }
        event_data = _make_webhook_event("subscription.renewed", payload)

        result = await webhook_service.process_webhook(event_data, "wh_renew_nulls")

        assert result.status == "processed"
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "active"
        assert "next_billing_date" not in set_data
        assert "previous_billing_date" not in set_data

    async def test_warns_when_subscription_not_found(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        """If update_one matches zero docs, a warning is logged (not a failure)."""
        mock_webhook_subscription_repository.apply_update_by_dodo_id = AsyncMock(return_value=False)
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event_data, "wh_renew_002")

        # Still processed, just with a warning
        assert result.status == "processed"
        mock_track_subscription.assert_not_called()

    async def test_tracks_renewal_analytics(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

        await webhook_service.process_webhook(event_data, "wh_renew_003")

        # WHICH subscription was resolved to a user. Unasserted, the lookup
        # argument could go null and the renewal would be attributed to
        # whoever a None lookup happens to return — or to nobody.
        mock_webhook_subscription_repository.get_user_id_by_dodo_id.assert_awaited_once_with(
            "sub_xyz789"
        )
        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:renewed"
        assert call_kwargs["user_id"] == FAKE_USER_ID
        assert call_kwargs["subscription_id"] == "sub_xyz789"


class TestHandleSubscriptionCancelled:
    """Tests for _handle_subscription_cancelled."""

    async def test_sets_status_to_cancelled(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_cancel_sub_001")

        assert result.status == "processed"
        assert "cancelled" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "cancelled"

    async def test_includes_cancelled_at_when_present(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "cancelled_at": "2025-06-15T00:00:00Z",
        }
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_002")

        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["cancelled_at"] == "2025-06-15T00:00:00Z"

    async def test_no_cancelled_at_when_absent(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "cancelled_at": None}
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_003")

        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert "cancelled_at" not in set_data

    async def test_tracks_cancellation_analytics(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_cancel_sub_004")

        mock_webhook_subscription_repository.get_user_id_by_dodo_id.assert_awaited_once_with(
            "sub_xyz789"
        )
        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:cancelled"
        assert call_kwargs["user_id"] == FAKE_USER_ID
        assert call_kwargs["properties"] == {
            "product_id": "prod_abc123",
            "billing_interval": "month",
        }

    async def test_scheduled_cancel_keeps_status_and_sets_flag(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        """A cancel-at-next-billing-date keeps the subscription active and just
        records the flag — the user retains Pro access until the period ends."""
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "status": "active",
            "cancel_at_next_billing_date": True,
        }
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_005")

        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        # Status is deliberately NOT in the update — only the flag records the
        # scheduled cancellation. A later `subscription.expired` flips status.
        assert "status" not in set_data
        assert set_data["cancel_at_next_billing_date"] is True

    async def test_scheduled_cancel_ignores_payload_status(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        """Even if Dodo ever reported status "cancelled" in a scheduled-cancel
        payload, the user is not downgraded early — status stays untouched."""
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "status": "cancelled",
            "cancel_at_next_billing_date": True,
        }
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_006")

        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert "status" not in set_data
        assert set_data["cancel_at_next_billing_date"] is True


class TestHandleSubscriptionExpired:
    """Tests for _handle_subscription_expired."""

    async def test_sets_status_to_expired(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.expired", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_expire_001")

        assert result.status == "processed"
        assert "expired" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "expired"

    async def test_tracks_expiry_analytics(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.expired", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_expire_002")

        mock_webhook_subscription_repository.get_user_id_by_dodo_id.assert_awaited_once_with(
            "sub_xyz789"
        )
        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:expired"
        assert call_kwargs["user_id"] == FAKE_USER_ID


class TestHandleSubscriptionFailed:
    """Tests for _handle_subscription_failed."""

    async def test_sets_status_to_failed(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
    ):
        event_data = _make_webhook_event("subscription.failed", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_sfail_001")

        assert result.status == "processed"
        assert "failed" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "failed"


class TestHandleSubscriptionOnHold:
    """Tests for _handle_subscription_on_hold."""

    async def test_sets_status_to_on_hold(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
    ):
        event_data = _make_webhook_event("subscription.on_hold", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_hold_001")

        assert result.status == "processed"
        assert "on hold" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "on_hold"


class TestHandleSubscriptionPlanChanged:
    """Tests for _handle_subscription_plan_changed."""

    async def test_updates_product_and_amount(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
    ):
        event_data = _make_webhook_event("subscription.plan_changed", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_change_001")

        assert result.status == "processed"
        assert "plan changed" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["product_id"] == "prod_abc123"
        assert set_data["quantity"] == 1
        assert set_data["recurring_pre_tax_amount"] == 999


# ============================================================================
# Webhook Helper Methods
# ============================================================================


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
        _set_user(mock_webhook_users_collection, None)

        await webhook_service._send_welcome_email(FAKE_USER_ID)

        mock_webhook_send_email.assert_not_awaited()

    async def test_no_email_when_user_has_no_email(
        self,
        webhook_service,
        mock_webhook_users_collection,
        mock_webhook_send_email,
    ):
        _set_user(mock_webhook_users_collection, {**SAMPLE_USER_DOC, "email": None})

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


class TestGetUserIdFromMetadata:
    """Tests for _get_user_id_from_metadata."""

    async def test_returns_user_id_when_present(self, webhook_service):
        user_id = await webhook_service._get_user_id_from_metadata({"user_id": FAKE_USER_ID})
        assert user_id == FAKE_USER_ID

    async def test_returns_none_when_no_user_id(self, webhook_service):
        user_id = await webhook_service._get_user_id_from_metadata({})
        assert user_id is None

    async def test_stringifies_non_string_user_id(self, webhook_service):
        user_id = await webhook_service._get_user_id_from_metadata({"user_id": 12345})
        assert user_id == "12345"


class TestIsWebhookProcessed:
    """Tests for _is_webhook_processed."""

    async def test_returns_true_when_found(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        mock_processed_webhook_repository.is_processed = AsyncMock(return_value=True)

        result = await webhook_service._is_webhook_processed("wh_exists")
        assert result is True

    async def test_returns_false_when_not_found(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        mock_processed_webhook_repository.is_processed = AsyncMock(return_value=False)

        result = await webhook_service._is_webhook_processed("wh_new")
        assert result is False


class TestMarkWebhookAsProcessed:
    """Tests for _mark_webhook_as_processed."""

    async def test_inserts_processed_record(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        result = DodoWebhookProcessingResult(
            event_type="payment.succeeded",
            status="processed",
            message="OK",
            payment_id="pay_001",
            subscription_id="sub_001",
        )

        await webhook_service._mark_webhook_as_processed("wh_mark_001", "payment.succeeded", result)

        mock_processed_webhook_repository.mark_processed.assert_awaited_once()
        call = mock_processed_webhook_repository.mark_processed.call_args
        assert call.args[0] == "wh_mark_001"
        assert call.kwargs["event_type"] == "payment.succeeded"
        assert call.kwargs["status"] == "processed"
        assert call.kwargs["payment_id"] == "pay_001"
        assert call.kwargs["subscription_id"] == "sub_001"

    async def test_insert_error_is_swallowed(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        """If storing webhook record fails, it's logged not propagated."""
        mock_processed_webhook_repository.mark_processed = AsyncMock(
            side_effect=Exception("DB write failed")
        )

        result = DodoWebhookProcessingResult(
            event_type="payment.succeeded",
            status="processed",
            message="OK",
        )

        # Should not raise
        await webhook_service._mark_webhook_as_processed("wh_mark_002", "payment.succeeded", result)


# ============================================================================
# PaymentWebhookService Initialization Tests
# ============================================================================


class TestPaymentWebhookServiceInit:
    """Tests for PaymentWebhookService.__init__."""

    def test_no_secret_disables_verifier(self):
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "development"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None

    def test_none_secret_disables_verifier(self):
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = None
            mock_settings.ENV = "development"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None

    def test_all_handler_event_types_registered(self):
        """All DodoWebhookEventType values have a corresponding handler."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "development"
            svc = PaymentWebhookService()

        for event_type in DodoWebhookEventType:
            assert event_type in svc.handlers, f"Missing handler for {event_type}"


# ============================================================================
# process_webhook account-sync scheduling
# ============================================================================


class TestWebhookAccountSync:
    """process_webhook schedules a workspace account sync for the metadata user
    after an event is processed — and only then."""

    @pytest.fixture
    def mock_schedule_sync(self):
        with patch(
            "app.services.payments.payment_webhook_service.schedule_account_sync"
        ) as mock_fn:
            yield mock_fn

    async def test_processed_event_schedules_sync_for_the_metadata_user(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_track_payment,
        mock_schedule_sync,
    ):
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event_data, "wh_sync_001")

        assert result.status == "processed"
        # The sync must target the user named in the payload's metadata.
        mock_schedule_sync.assert_called_once_with(FAKE_USER_ID)

    async def test_failed_result_does_not_schedule_sync(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_track_payment,
        mock_schedule_sync,
    ):
        """Only processed billing changes refresh the projection — a failed
        handler must not, even when the payload carries a user id."""
        failed = DodoWebhookProcessingResult(
            event_type=DodoWebhookEventType.PAYMENT_SUCCEEDED.value,
            status="failed",
            message="handler declined",
        )
        original_handlers = webhook_service.handlers.copy()
        webhook_service.handlers[DodoWebhookEventType.PAYMENT_SUCCEEDED] = AsyncMock(
            return_value=failed
        )
        try:
            event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
            result = await webhook_service.process_webhook(event_data, "wh_sync_002")
        finally:
            webhook_service.handlers = original_handlers

        assert result.status == "failed"
        mock_schedule_sync.assert_not_called()

    async def test_non_string_metadata_user_id_is_never_scheduled(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_track_payment,
        mock_schedule_sync,
    ):
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {"user_id": 12345}}
        event_data = _make_webhook_event("payment.succeeded", payload)

        result = await webhook_service.process_webhook(event_data, "wh_sync_003")

        assert result.status == "processed"
        mock_schedule_sync.assert_not_called()


# ============================================================================
# process_webhook customer_id extraction
# ============================================================================


class TestProcessWebhookCustomerIdExtraction:
    """Verify customer_id is correctly extracted from nested and flat payloads."""

    async def test_extracts_customer_id_from_nested_customer_dict(
        self,
        webhook_service,
        mock_processed_webhook_repository,
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
        mock_processed_webhook_repository,
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
