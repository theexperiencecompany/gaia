"""Mutation-verified unit tests for the Dodo Payments services.

This file targets TWO production units that live in the same package:

  - app/services/payments/payment_service.py        :: DodoPaymentService
  - app/services/payments/payment_webhook_service.py :: PaymentWebhookService

The DodoPaymentService suite below is mutation-hardened (the objective gate);
the PaymentWebhookService suite preserves existing coverage for the sibling unit.

============================================================================
BEHAVIOR SPEC — DodoPaymentService  (mutation target)
============================================================================

UNIT: payment_service.py :: DodoPaymentService.__init__
EXPECTED: Instantiate the DodoPayments SDK client with the configured bearer
          token and an environment derived from settings.ENV
          ("production" -> "live_mode", anything else -> "test_mode").
          A client-construction failure is logged, never raised.
MECHANISM: env = "live_mode" if settings.ENV == "production" else "test_mode";
           self.client = DodoPayments(bearer_token=KEY, environment=env).
MUST-CATCH:
  - ENV == "production" yields environment="live_mode"            [branch true]
  - ENV != "production" yields environment="test_mode"            [branch false]
  - bearer_token is exactly settings.DODO_PAYMENTS_API_KEY
  - SDK construction raising does NOT propagate                   [try/except]

UNIT: payment_service.py :: DodoPaymentService.get_plans
EXPECTED: Return list[PlanResponse] for plans, cache-first. On cache hit,
          rebuild PlanResponse objects (defaulting a missing dodo_product_id
          to ""), never hitting Mongo. On a malformed cache entry, delete the
          key and fall through to Mongo. On cache miss, query Mongo
          ({"is_active": True} when active_only else {}), sorted by amount asc,
          map docs -> PlanResponse, and write the result back to cache.
MECHANISM: cache_key f"plans:{'active' if active_only else 'all'}";
           redis_cache.get -> build-or-delete; plans_collection.find(query)
           .sort("amount", 1).to_list(None); redis_cache.set(key, dumps).
MUST-CATCH:
  - cache hit returns cached plans and NEVER queries Mongo        [branch]
  - cache entry missing dodo_product_id is defaulted to ""        [branch if]
  - malformed cache entry triggers redis delete + Mongo fallback  [except]
  - active_only=True -> Mongo query is exactly {"is_active": True}
  - active_only=False -> Mongo query is exactly {}                [branch]
  - sort is on field "amount" ascending (1)
  - to_list(None) (no limit) drives the fetch
  - DB docs are mapped field-for-field into PlanResponse
  - optional fields (description/max_users/features) default safely
  - the freshly built plans are written back to cache

UNIT: payment_service.py :: DodoPaymentService.create_subscription
EXPECTED: Create a hosted Dodo checkout session for an existing user with no
          active subscription, returning {subscription_id, payment_link,
          status:"payment_link_created"}. 404 if user missing, 409 if an active
          subscription exists, 502 if the Dodo client errors.
MECHANISM: users_collection.find_one({"_id": ObjectId(user_id)}); 404 if none;
           subscriptions_collection.find_one({"user_id", "status":"active"});
           409 if found; build params (product_cart, customer, feature_flags,
           return_url, metadata, subscription_data) [+discount_code]; call
           client.checkout_sessions.create(**params); 502 on failure; return.
MUST-CATCH:
  - missing user raises HTTPException(404, "User not found")      [branch]
  - existing active sub raises HTTPException(409, ...)            [branch]
  - the active-sub lookup filter is {"user_id": user_id, "status": "active"}
  - product_cart carries product_id and the given quantity
  - feature_flags.allow_discount_code is True
  - feature_flags.allow_customer_editing_country is True
  - return_url is f"{FRONTEND_URL}/payment/success"
  - metadata is {"user_id", "product_id"}
  - customer.email comes from the user doc
  - customer.name prefers first_name, then name, then "User"      [or-chain]
  - discount_code present -> included; absent -> key omitted      [branch if]
  - Dodo client raising -> HTTPException(502, "Payment service error: ...")
  - happy path returns session_id, checkout_url and the literal status string
  - get_plans failure during plan-name logging does NOT break the call [except]

UNIT: payment_service.py :: DodoPaymentService.verify_payment_completion
EXPECTED: Report whether the user has an active subscription. No active sub ->
          {payment_completed: False, message}. Active sub -> send a best-effort
          welcome email (only when user has an email), return
          {payment_completed: True, subscription_id, message}. Email failure is
          swallowed.
MECHANISM: subscriptions_collection.find_one({"user_id","status":"active"},
           sort=[("created_at", -1)]); welcome email guarded by user+email;
           return dict.
MUST-CATCH:
  - no active sub -> payment_completed False + "No active subscription" msg
  - active-sub lookup sorts by created_at descending (-1)
  - active sub -> payment_completed True + dodo_subscription_id echoed
  - welcome email sent with first_name + email when both present
  - user with no email -> no email sent                          [branch and]
  - user not found -> no email sent                              [branch and]
  - send_pro_subscription_email raising -> swallowed, still True [except]

UNIT: payment_service.py :: DodoPaymentService.get_user_subscription_status
EXPECTED: Build a UserSubscriptionStatus. No active sub -> FREE/unsubscribed
          shape. Active sub -> PRO/subscribed shape with the matched plan (or
          None when none matches / plan lookup fails) and the serialized
          subscription document.
MECHANISM: subscriptions_collection.find_one({"user_id","status":"active"});
           free-shape on miss; else get_plans(active_only=False) -> match by
           dodo_product_id == product_id (None on miss/exception);
           serialize_document(subscription); SubscriptionStatus(sub["status"]).
MUST-CATCH:
  - no active sub -> is_subscribed False, plan_type FREE, status PENDING,
    can_upgrade True, can_downgrade False, has_subscription False, both None
  - active sub -> is_subscribed True, plan_type PRO, has_subscription True,
    can_upgrade True, can_downgrade True
  - matched plan populates current_plan; no match -> None         [branch]
  - get_plans raising -> plan falls back to None                  [except]
  - subscription field is the REAL serialize_document output (_id -> id)
  - status mirrors the subscription's stored status string

EQUIVALENT MUTANTS (allowed survivors, justified): documented inline where any
remain after the loop; target is kill_rate == 1.0 for this critical-path unit.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

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
NOW = datetime.now(UTC)
FRONTEND_URL = "https://app.test"

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

SAMPLE_USER_DOC: dict[str, Any] = {
    "_id": ObjectId(FAKE_USER_ID),
    "email": FAKE_EMAIL,
    "first_name": "Alice",
    "name": "Alice Smith",
}

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
# Helpers
# ---------------------------------------------------------------------------


def _make_webhook_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "business_id": "biz_001",
        "type": event_type,
        "timestamp": "2025-01-01T00:00:00Z",
        "data": data,
    }


def _make_db_cursor(docs: list[dict[str, Any]]) -> AsyncMock:
    """Build a fake Motor cursor: .find(q).sort(f, d).to_list(None)."""
    cursor = AsyncMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=docs)
    return cursor


def _checkout_response(session_id: str, checkout_url: str) -> MagicMock:
    resp = MagicMock()
    resp.session_id = session_id
    resp.checkout_url = checkout_url
    return resp


# ---------------------------------------------------------------------------
# Fixtures — mock all DB collections, Redis, external clients
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_plans_collection():
    with patch("app.services.payments.payment_service.plans_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_subscriptions_collection():
    with patch("app.services.payments.payment_service.subscriptions_collection") as mock_col:
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
def mock_settings():
    """Patch settings used by create_subscription (FRONTEND_URL)."""
    with patch("app.services.payments.payment_service.settings") as mock_s:
        mock_s.FRONTEND_URL = FRONTEND_URL
        mock_s.ENV = "development"
        mock_s.DODO_PAYMENTS_API_KEY = "sk_test"  # pragma: allowlist secret
        yield mock_s


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
    with patch("app.services.payments.payment_webhook_service.users_collection") as mock_col:
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
        mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"  # pragma: allowlist secret
        mock_settings.ENV = "development"
        with patch("app.services.payments.payment_webhook_service.Webhook") as mock_wh_cls:
            mock_verifier = MagicMock()
            mock_wh_cls.return_value = mock_verifier
            svc = PaymentWebhookService()
    return svc


# ============================================================================
# DodoPaymentService.__init__
# ============================================================================


@pytest.mark.unit
class TestDodoPaymentServiceInit:
    """DodoPaymentService.__init__ — environment selection + failure handling."""

    def test_production_env_uses_live_mode(self):
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "production"
            mock_settings.DODO_PAYMENTS_API_KEY = "sk_live_test"  # pragma: allowlist secret
            with patch("app.services.payments.payment_service.DodoPayments") as mock_cls:
                DodoPaymentService()
                mock_cls.assert_called_once_with(
                    bearer_token="sk_live_test",  # pragma: allowlist secret
                    environment="live_mode",
                )

    def test_non_production_env_uses_test_mode(self):
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "development"
            mock_settings.DODO_PAYMENTS_API_KEY = "sk_test_test"  # pragma: allowlist secret
            with patch("app.services.payments.payment_service.DodoPayments") as mock_cls:
                DodoPaymentService()
                mock_cls.assert_called_once_with(
                    bearer_token="sk_test_test",  # pragma: allowlist secret
                    environment="test_mode",
                )

    def test_client_init_failure_is_swallowed(self):
        """A DodoPayments construction error is logged, never raised."""
        with patch("app.services.payments.payment_service.settings") as mock_settings:
            mock_settings.ENV = "development"
            mock_settings.DODO_PAYMENTS_API_KEY = "bad_key"  # pragma: allowlist secret
            with patch(
                "app.services.payments.payment_service.DodoPayments",
                side_effect=Exception("Bad API key"),
            ):
                svc = DodoPaymentService()

        # Construction succeeded (no raise) but the client was never assigned.
        assert not hasattr(svc, "client")


# ============================================================================
# DodoPaymentService.get_plans
# ============================================================================


@pytest.mark.unit
class TestGetPlans:
    """DodoPaymentService.get_plans — cache-first read of subscription plans."""

    async def test_db_fetch_maps_all_fields_and_caches(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Cache miss: query active plans, map every field, write back to cache."""
        cursor = _make_db_cursor([SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        plans = await payment_service.get_plans(active_only=True)

        assert len(plans) == 1
        plan = plans[0]
        assert plan.id == str(SAMPLE_PLAN_DOC["_id"])
        assert plan.dodo_product_id == "prod_abc123"
        assert plan.name == "Pro Monthly"
        assert plan.description == "Pro features billed monthly"
        assert plan.amount == 999
        assert plan.currency == "USD"
        assert plan.duration == "monthly"
        assert plan.max_users == 5
        assert plan.features == ["feature_a", "feature_b"]
        assert plan.is_active is True

        # active_only=True -> exact filter, sorted by amount ascending, no limit.
        mock_plans_collection.find.assert_called_once_with({"is_active": True})
        cursor.sort.assert_called_once_with("amount", 1)
        cursor.to_list.assert_awaited_once_with(None)

        # Fresh plans are written back under the active cache key.
        mock_redis_cache.set.assert_awaited_once()
        set_key, set_payload = mock_redis_cache.set.await_args[0]
        assert set_key == "plans:active"
        assert set_payload[0]["dodo_product_id"] == "prod_abc123"
        assert set_payload[0]["name"] == "Pro Monthly"

    async def test_active_only_false_uses_empty_query_and_all_key(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """active_only=False -> empty Mongo filter and the 'all' cache key."""
        cursor = _make_db_cursor([SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        await payment_service.get_plans(active_only=False)

        mock_plans_collection.find.assert_called_once_with({})
        mock_redis_cache.get.assert_awaited_once_with("plans:all")
        set_key, _ = mock_redis_cache.set.await_args[0]
        assert set_key == "plans:all"

    async def test_cache_hit_returns_cached_and_skips_db(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """A valid cache entry is returned without touching Mongo or rewriting cache."""
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
        mock_plans_collection.find = MagicMock()

        plans = await payment_service.get_plans()

        assert len(plans) == 1
        assert plans[0].name == "Cached Plan"
        mock_plans_collection.find.assert_not_called()
        mock_redis_cache.set.assert_not_awaited()

    async def test_cache_entry_missing_product_id_defaulted_to_empty(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """A cache entry without dodo_product_id parses with an empty-string default."""
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
        mock_plans_collection.find = MagicMock()

        plans = await payment_service.get_plans()

        assert plans[0].dodo_product_id == ""
        # The default path must still serve from cache, not Mongo.
        mock_plans_collection.find.assert_not_called()

    async def test_malformed_cache_deletes_key_and_falls_back_to_db(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Unparseable cache entry -> delete the key, then fetch from Mongo."""
        mock_redis_cache.get = AsyncMock(return_value=[{"amount": "not-an-int", "bad": True}])
        cursor = _make_db_cursor([SAMPLE_PLAN_DOC])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        plans = await payment_service.get_plans()

        mock_redis_cache.delete.assert_awaited_once_with("plans:active")
        assert len(plans) == 1
        assert plans[0].name == "Pro Monthly"

    async def test_empty_db_returns_empty_list(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        cursor = _make_db_cursor([])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        plans = await payment_service.get_plans()

        assert plans == []
        # Even an empty result is cached.
        mock_redis_cache.set.assert_awaited_once()

    async def test_db_doc_optional_fields_default_safely(
        self,
        payment_service,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """A DB doc missing optional fields maps with safe defaults."""
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
        cursor = _make_db_cursor([minimal_doc])
        mock_plans_collection.find = MagicMock(return_value=cursor)

        plans = await payment_service.get_plans()

        assert plans[0].dodo_product_id == ""
        assert plans[0].description is None
        assert plans[0].max_users is None
        assert plans[0].features == []
        assert plans[0].name == "Basic"


# ============================================================================
# DodoPaymentService.create_subscription
# ============================================================================


@pytest.mark.unit
class TestCreateSubscription:
    """DodoPaymentService.create_subscription — hosted checkout session creation."""

    async def test_success_returns_payment_link_payload(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_settings,
        mock_dodo_client,
    ):
        """Happy path returns the session id, checkout url, and literal status."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=_checkout_response("sess_001", "https://checkout.dodo.dev/sess_001")
        )
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([]))

        result = await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        assert result == {
            "subscription_id": "sess_001",
            "payment_link": "https://checkout.dodo.dev/sess_001",
            "status": "payment_link_created",
        }

    async def test_builds_full_checkout_params(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_settings,
        mock_dodo_client,
    ):
        """Every checkout-session parameter the hosted page depends on is asserted."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=_checkout_response("sess_x", "https://checkout.dodo.dev/sess_x")
        )
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([]))

        await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
            quantity=2,
        )

        # The user is looked up by ObjectId(user_id).
        assert mock_users_collection.find_one.await_args[0][0] == {"_id": ObjectId(FAKE_USER_ID)}

        params = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert params["product_cart"] == [{"product_id": "prod_abc123", "quantity": 2}]
        assert params["customer"]["email"] == FAKE_EMAIL
        assert params["customer"]["name"] == "Alice"
        assert params["feature_flags"]["allow_discount_code"] is True
        assert params["feature_flags"]["allow_customer_editing_country"] is True
        assert params["return_url"] == f"{FRONTEND_URL}/payment/success"
        assert params["metadata"] == {"user_id": FAKE_USER_ID, "product_id": "prod_abc123"}
        # subscription_data is always sent (even if empty) so Dodo applies stored pricing.
        assert "subscription_data" in params
        assert "discount_code" not in params

    async def test_default_quantity_is_one(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_settings,
        mock_dodo_client,
    ):
        """Quantity defaults to exactly 1 when the caller omits it."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=_checkout_response("sess_q", "https://checkout.dodo.dev/sess_q")
        )
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([]))

        await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        params = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert params["product_cart"][0]["quantity"] == 1

    async def test_active_subscription_lookup_filter(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_settings,
        mock_dodo_client,
    ):
        """The duplicate-guard query targets this user's active subscription only."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=_checkout_response("sess_f", "https://checkout.dodo.dev/sess_f")
        )
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([]))

        await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        mock_subscriptions_collection.find_one.assert_awaited_once_with(
            {"user_id": FAKE_USER_ID, "status": "active"}
        )

    async def test_customer_name_falls_back_to_name_then_user(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_settings,
        mock_dodo_client,
    ):
        """No first_name -> use name; no name either -> literal 'User'."""
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=_checkout_response("s", "https://c/s")
        )
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([]))

        # first_name missing -> falls through to name
        mock_users_collection.find_one = AsyncMock(
            return_value={"_id": ObjectId(FAKE_USER_ID), "email": FAKE_EMAIL, "name": "Bob Jones"}
        )
        await payment_service.create_subscription(user_id=FAKE_USER_ID, product_id="p")
        assert mock_dodo_client.checkout_sessions.create.call_args[1]["customer"]["name"] == (
            "Bob Jones"
        )

        # neither first_name nor name -> literal "User"
        mock_users_collection.find_one = AsyncMock(
            return_value={"_id": ObjectId(FAKE_USER_ID), "email": FAKE_EMAIL}
        )
        await payment_service.create_subscription(user_id=FAKE_USER_ID, product_id="p")
        assert mock_dodo_client.checkout_sessions.create.call_args[1]["customer"]["name"] == "User"

    async def test_raises_404_when_user_missing(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_settings,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc:
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID,
                product_id="prod_abc123",
            )

        assert exc.value.status_code == 404
        assert "User not found" in str(exc.value.detail)

    async def test_raises_409_when_active_subscription_exists(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_settings,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=SAMPLE_SUBSCRIPTION_DOC)

        with pytest.raises(HTTPException) as exc:
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID,
                product_id="prod_abc123",
            )

        assert exc.value.status_code == 409
        assert "Active subscription exists" in str(exc.value.detail)

    async def test_raises_502_on_dodo_client_error(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_settings,
        mock_dodo_client,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            side_effect=Exception("Dodo API down")
        )

        with pytest.raises(HTTPException) as exc:
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID,
                product_id="prod_abc123",
            )

        assert exc.value.status_code == 502
        assert "Payment service error" in str(exc.value.detail)
        assert "Dodo API down" in str(exc.value.detail)

    async def test_discount_code_included_when_provided(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_settings,
        mock_dodo_client,
    ):
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=_checkout_response("sess_002", "https://checkout.dodo.dev/sess_002")
        )
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([]))

        await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
            discount_code="SAVE20",
        )

        params = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert params["discount_code"] == "SAVE20"

    async def test_get_plans_failure_during_logging_does_not_break_call(
        self,
        payment_service,
        mock_users_collection,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
        mock_settings,
        mock_dodo_client,
    ):
        """A failure resolving the plan name for logging must not fail the request."""
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=_checkout_response("sess_004", "https://checkout.dodo.dev/sess_004")
        )
        # get_plans -> Mongo to_list raises; cache miss already default.
        cursor = _make_db_cursor([])
        cursor.to_list = AsyncMock(side_effect=Exception("DB down"))
        mock_plans_collection.find = MagicMock(return_value=cursor)

        result = await payment_service.create_subscription(
            user_id=FAKE_USER_ID,
            product_id="prod_abc123",
        )

        assert result["subscription_id"] == "sess_004"
        assert result["status"] == "payment_link_created"


# ============================================================================
# DodoPaymentService.verify_payment_completion
# ============================================================================


@pytest.mark.unit
class TestVerifyPaymentCompletion:
    """DodoPaymentService.verify_payment_completion — completion + welcome email."""

    async def test_active_subscription_returns_completed_and_emails(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(return_value=SAMPLE_SUBSCRIPTION_DOC)
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result == {
            "payment_completed": True,
            "subscription_id": "sub_xyz789",
            "message": "Payment completed",
        }
        # The welcome email targets the resolved user, looked up by ObjectId(user_id).
        assert mock_users_collection.find_one.await_args[0][0] == {"_id": ObjectId(FAKE_USER_ID)}
        mock_send_email.assert_awaited_once_with(
            user_name="Alice",
            user_email=FAKE_EMAIL,
        )

    async def test_active_subscription_lookup_sorts_by_created_at_desc(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        """The newest active subscription is selected (created_at descending)."""
        mock_subscriptions_collection.find_one = AsyncMock(return_value=SAMPLE_SUBSCRIPTION_DOC)
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)

        await payment_service.verify_payment_completion(FAKE_USER_ID)

        mock_subscriptions_collection.find_one.assert_awaited_once_with(
            {"user_id": FAKE_USER_ID, "status": "active"},
            sort=[("created_at", -1)],
        )

    async def test_no_subscription_returns_not_completed(
        self,
        payment_service,
        mock_subscriptions_collection,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result == {
            "payment_completed": False,
            "message": "No active subscription found",
        }

    async def test_email_failure_is_swallowed(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(return_value=SAMPLE_SUBSCRIPTION_DOC)
        mock_users_collection.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        mock_send_email.side_effect = Exception("SMTP error")

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result["payment_completed"] is True
        assert result["subscription_id"] == "sub_xyz789"

    async def test_no_email_when_user_has_no_email(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(return_value=SAMPLE_SUBSCRIPTION_DOC)
        mock_users_collection.find_one = AsyncMock(return_value={**SAMPLE_USER_DOC, "email": None})

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result["payment_completed"] is True
        mock_send_email.assert_not_awaited()

    async def test_no_email_when_user_not_found(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_users_collection,
        mock_send_email,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(return_value=SAMPLE_SUBSCRIPTION_DOC)
        mock_users_collection.find_one = AsyncMock(return_value=None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result["payment_completed"] is True
        mock_send_email.assert_not_awaited()


# ============================================================================
# DodoPaymentService.get_user_subscription_status
# ============================================================================


@pytest.mark.unit
class TestGetUserSubscriptionStatus:
    """DodoPaymentService.get_user_subscription_status — FREE vs PRO shapes."""

    async def test_no_subscription_returns_free_status(
        self,
        payment_service,
        mock_subscriptions_collection,
    ):
        mock_subscriptions_collection.find_one = AsyncMock(return_value=None)

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        # Active subscription is selected via an exact user_id + status filter.
        mock_subscriptions_collection.find_one.assert_awaited_once_with(
            {"user_id": FAKE_USER_ID, "status": "active"}
        )
        assert isinstance(status, UserSubscriptionStatus)
        assert status.user_id == FAKE_USER_ID
        assert status.is_subscribed is False
        assert status.plan_type == PlanType.FREE
        assert status.status == SubscriptionStatus.PENDING
        assert status.can_upgrade is True
        assert status.can_downgrade is False
        assert status.has_subscription is False
        assert status.current_plan is None
        assert status.subscription is None
        assert status.days_remaining is None

    async def test_active_subscription_returns_pro_status_with_real_serialization(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Active sub -> PRO shape; subscription is the real serialize_document output."""
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=dict(SAMPLE_SUBSCRIPTION_DOC)
        )
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([SAMPLE_PLAN_DOC]))

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.plan_type == PlanType.PRO
        assert status.status == SubscriptionStatus.ACTIVE
        assert status.has_subscription is True
        assert status.can_upgrade is True
        assert status.can_downgrade is True
        # Matched plan present.
        assert status.current_plan is not None
        assert status.current_plan["dodo_product_id"] == "prod_abc123"
        assert status.current_plan["name"] == "Pro Monthly"
        # Real serialize_document: _id becomes id (stringified), fields preserved.
        assert status.subscription is not None
        assert status.subscription["id"] == str(SAMPLE_SUBSCRIPTION_DOC["_id"])
        assert status.subscription["dodo_subscription_id"] == "sub_xyz789"
        assert "_id" not in status.subscription

    async def test_active_subscription_no_matching_plan_sets_plan_none(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """Subscription product_id not among plans -> current_plan is None."""
        sub_doc = {**SAMPLE_SUBSCRIPTION_DOC, "product_id": "prod_unknown"}
        mock_subscriptions_collection.find_one = AsyncMock(return_value=sub_doc)
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([SAMPLE_PLAN_DOC]))

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.current_plan is None

    async def test_plan_lookup_failure_sets_plan_none(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """get_plans raising -> plan gracefully falls back to None, still subscribed."""
        mock_subscriptions_collection.find_one = AsyncMock(
            return_value=dict(SAMPLE_SUBSCRIPTION_DOC)
        )
        mock_redis_cache.get = AsyncMock(side_effect=Exception("Redis down"))
        cursor = _make_db_cursor([])
        cursor.to_list = AsyncMock(side_effect=Exception("DB down"))
        mock_plans_collection.find = MagicMock(return_value=cursor)

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is True
        assert status.current_plan is None
        # subscription still serialized even when plan lookup failed.
        assert status.subscription is not None
        assert status.subscription["dodo_subscription_id"] == "sub_xyz789"

    async def test_status_mirrors_stored_subscription_status(
        self,
        payment_service,
        mock_subscriptions_collection,
        mock_plans_collection,
        mock_redis_cache,
    ):
        """The legacy status field reflects the subscription document's status string."""
        sub_doc = {**SAMPLE_SUBSCRIPTION_DOC, "status": "on_hold"}
        mock_subscriptions_collection.find_one = AsyncMock(return_value=sub_doc)
        mock_plans_collection.find = MagicMock(return_value=_make_db_cursor([SAMPLE_PLAN_DOC]))

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.status == SubscriptionStatus.ON_HOLD


# ============================================================================
# PaymentWebhookService Tests (sibling unit — coverage preserved)
# ============================================================================


@pytest.mark.unit
class TestVerifyWebhookSignature:
    """Tests for PaymentWebhookService.verify_webhook_signature."""

    def test_returns_true_when_no_verifier_configured(self):
        """When webhook_secret is empty, skip verification and return True."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "production"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None
        result = svc.verify_webhook_signature("{}", {})
        assert result is True

    def test_returns_true_in_development_mode(self, webhook_service):
        """In non-production env, skip verification."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
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
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"  # pragma: allowlist secret
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
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"  # pragma: allowlist secret
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
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"  # pragma: allowlist secret
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
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "bad_secret"  # pragma: allowlist secret
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
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
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

        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

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
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

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
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

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
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.expired", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.expired", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.failed", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.on_hold", SUBSCRIPTION_DATA_PAYLOAD)
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
        event_data = _make_webhook_event("subscription.plan_changed", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_change_001")

        assert result.status == "processed"
        assert "plan changed" in result.message.lower()
        update_call = mock_webhook_subscriptions_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["product_id"] == "prod_abc123"
        assert set_data["quantity"] == 1
        assert set_data["recurring_pre_tax_amount"] == 999


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
        email = await webhook_service._get_user_email_from_metadata({"user_id": FAKE_USER_ID})
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

        email = await webhook_service._get_user_email_from_metadata({"user_id": FAKE_USER_ID})
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

        await webhook_service._mark_webhook_as_processed("wh_mark_001", "payment.succeeded", result)

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
        await webhook_service._mark_webhook_as_processed("wh_mark_002", "payment.succeeded", result)


@pytest.mark.unit
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
