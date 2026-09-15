"""
Unit tests for DodoPaymentService.

Covers: get_plans, create_subscription, verify_payment_completion,
get_user_subscription_status.

PaymentWebhookService tests live in ``test_payment_webhook_service.py``; both
files share fixtures and fake data via ``conftest.py`` in this directory.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from bson import ObjectId
from dodopayments.types import Subscription
from fastapi import HTTPException
import pytest

from app.constants.cache import (
    ACTIVE_PLANS_CACHE_KEY,
    CHECKOUT_SCAN_MISS_CACHE_PREFIX,
    CHECKOUT_SCAN_MISS_TTL,
)
from app.constants.log_tags import LogTag
from app.constants.payments import CHECKOUT_SESSION_SCAN_LIMIT, PAYMENT_HISTORY_LIMIT
from app.models.payment_models import (
    CheckoutSource,
    CreateSubscriptionResponse,
    PlanDocument,
    PlanDuration,
    PlanResponse,
    PlanType,
    SubscriptionDocument,
    SubscriptionStatus,
    UserSubscriptionStatus,
)
from app.services.analytics_service import AnalyticsEvents, SubscriptionPlan
from app.services.payments import payment_service as payment_service_module
from app.services.payments.payment_service import DodoPaymentService
from app.services.payments.subscription_events import (
    SubscriptionEventKind,
    SubscriptionEventOutcome,
    SubscriptionEventResult,
)
from shared.py.wide_events import log
from tests.helpers import captured_wide_event
from tests.unit.services.conftest import (
    FAKE_EMAIL,
    FAKE_USER_ID,
    NOW,
    SAMPLE_SUBSCRIPTION,
    SAMPLE_SUBSCRIPTION_DOC,
    SAMPLE_USER_DOC,
    _set_user,
)

ACTIVATION_MODULE = "app.services.payments.subscription_events"
SERVICE_MODULE = "app.services.payments.payment_service"
OTHER_USER_ID = "507f1f77bcf86cd799439012"

# ---------------------------------------------------------------------------
# DodoPaymentService-only test data
# ---------------------------------------------------------------------------

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
        mock_repo.apply_update_by_dodo_id = AsyncMock(return_value=True)
        mock_repo.has_any_for_user = AsyncMock(return_value=False)
        yield mock_repo


@pytest.fixture
def mock_users_collection():
    with patch("app.services.payments.payment_service.user_repository") as mock_repo:
        _set_user(mock_repo, SAMPLE_USER_DOC)
        yield mock_repo


@pytest.fixture
def mock_plan_cache_invalidation():
    """The gate's cached tier is dropped through Redis; keep it in memory."""
    with patch(
        "app.services.payments.payment_service.invalidate_plan_cache", new_callable=AsyncMock
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_redis_cache():
    with patch("app.services.payments.payment_service.redis_cache") as mock_cache:
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.delete = AsyncMock()
        yield mock_cache


@pytest.fixture
def mock_dodo_client():
    client = MagicMock()
    client.checkout_sessions = MagicMock()
    return client


@pytest.fixture
def mock_checkout_session_repository():
    """No pending checkout by default — the Dodo fallback is skipped."""
    with patch("app.services.payments.payment_service.checkout_session_repository") as mock_repo:
        mock_repo.list_recent_for_user = AsyncMock(return_value=[])
        mock_repo.create = AsyncMock()
        yield mock_repo


@pytest.fixture
def payment_service(mock_dodo_client):
    """Create a DodoPaymentService with a mocked Dodo client."""
    with patch("app.services.payments.payment_service.DodoPayments") as mock_cls:
        mock_cls.return_value = mock_dodo_client
        svc = DodoPaymentService()
    svc.client = mock_dodo_client
    return svc


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
        # The cache mirrors the catalogue verbatim: the serialized plan list
        # under the active-plans key, nothing less.
        mock_redis_cache.set.assert_awaited_once_with(
            ACTIVE_PLANS_CACHE_KEY, [plans[0].model_dump()]
        )

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

    async def test_free_plan_never_reaches_the_response(
        self,
        payment_service,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """GAIA is paid-only — a $0 'Free' row in the collection must never
        render as a card, even though the repository still returns it (a
        pre-cutover seed, or a manual DB edit)."""
        free_plan = PlanDocument(
            id=str(ObjectId()),
            dodo_product_id="",
            name="Free",
            amount=0,
            currency="USD",
            duration="monthly",
            is_active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        mock_plan_repository.list_plans = AsyncMock(return_value=[free_plan, SAMPLE_PLAN])

        plans = await payment_service.get_plans()

        assert [p.name for p in plans] == ["Pro Monthly"]
        assert all(p.amount > 0 for p in plans)

    async def test_free_plan_filtered_even_when_served_from_cache(
        self,
        payment_service,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """The free row is cached too (the cache mirrors the DB) — filtering
        must happen on every read path, not only the DB-miss path."""
        cached_free = PlanResponse(
            id="free-id",
            dodo_product_id="",
            name="Free",
            description=None,
            amount=0,
            currency="USD",
            duration="monthly",
            max_users=1,
            features=[],
            is_active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        cached_pro = PlanResponse(
            id="pro-id",
            dodo_product_id="prod_abc123",
            name="Pro",
            description=None,
            amount=3000,
            currency="USD",
            duration="monthly",
            max_users=1,
            features=[],
            is_active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        mock_redis_cache.get = AsyncMock(
            return_value=[cached_free.model_dump(), cached_pro.model_dump()]
        )

        plans = await payment_service.get_plans()

        assert [p.name for p in plans] == ["Pro"]

    async def test_zero_amount_enterprise_plan_is_not_mistaken_for_free(
        self,
        payment_service,
        mock_plan_repository,
        mock_redis_cache,
    ):
        """Enterprise is also $0 (contact-sales) — amount alone must not be
        the filter, or the Enterprise card would vanish too."""
        enterprise_plan = PlanDocument(
            id=str(ObjectId()),
            dodo_product_id="",
            name="Enterprise",
            amount=0,
            currency="USD",
            duration="monthly",
            max_users=0,
            is_active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        mock_plan_repository.list_plans = AsyncMock(return_value=[enterprise_plan])

        plans = await payment_service.get_plans()

        assert [p.name for p in plans] == ["Enterprise"]


class TestCreateSubscription:
    """Tests for DodoPaymentService.create_subscription."""

    @pytest.mark.usefixtures(
        "mock_users_collection",
        "mock_subscription_repository",
        "mock_plan_repository",
        "mock_checkout_session_repository",
    )
    async def test_minting_a_new_checkout_forgets_the_cached_unpaid_scan(
        self, payment_service, mock_dodo_client, mock_redis_cache
    ):
        """ "None of your sessions is paid" was cached against the sessions that
        existed; a new one is not among them, so the verdict is void."""
        mock_dodo_client.checkout_sessions.create = MagicMock(
            return_value=SimpleNamespace(session_id="ches_new", checkout_url="https://pay/x")
        )

        await payment_service.create_subscription(FAKE_USER_ID, "prod_abc123")

        mock_redis_cache.delete.assert_awaited_once_with(
            f"{CHECKOUT_SCAN_MISS_CACHE_PREFIX}{FAKE_USER_ID}"
        )

    @pytest.mark.usefixtures("mock_redis_cache")
    async def test_success_returns_payment_link(
        self,
        payment_service,
        mock_users_collection,
        mock_subscription_repository,
        mock_plan_repository,
        mock_dodo_client,
        mock_checkout_session_repository,
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
        # The product's stored price is used as-is: no trial or price override
        # rides along under Dodo's ``subscription_data`` key.
        create_kwargs = mock_dodo_client.checkout_sessions.create.call_args.kwargs
        assert create_kwargs["subscription_data"] == {}
        # The checkout session is recorded verbatim — the verify fallback
        # resolves the purchase against Dodo through this record.
        recorded = mock_checkout_session_repository.create.call_args.args[0]
        assert recorded.session_id == "sess_001"
        assert recorded.user_id == FAKE_USER_ID
        assert recorded.product_id == "prod_abc123"
        assert recorded.created_at is not None
        assert recorded.created_at.tzinfo is not None

    @pytest.mark.usefixtures("mock_redis_cache")
    async def test_checkout_record_failure_does_not_block_checkout(
        self,
        payment_service,
        mock_users_collection,
        mock_subscription_repository,
        mock_plan_repository,
        mock_dodo_client,
        mock_checkout_session_repository,
    ):
        """Recording the session is best-effort: losing it only disables the
        verify fallback, never the checkout itself — but the loss is logged."""
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        checkout_response = MagicMock()
        checkout_response.session_id = "sess_001"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_001"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=checkout_response)
        mock_plan_repository.list_plans = AsyncMock(return_value=[])
        mock_checkout_session_repository.create = AsyncMock(side_effect=Exception("mongo down"))

        with patch("app.services.payments.payment_service.log") as mock_log:
            result = await payment_service.create_subscription(
                user_id=FAKE_USER_ID,
                product_id="prod_abc123",
            )

        assert result.subscription_id == "sess_001"
        assert result.status == "payment_link_created"
        mock_log.error.assert_called_once_with(
            f"{LogTag.PAYMENT} Failed to record checkout session",
            error="mongo down",
            error_type="Exception",
            user_id=FAKE_USER_ID,
            session_id="sess_001",
        )

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

    async def test_outside_production_everything_but_the_card_is_prefilled(
        self,
        payment_service,
        mock_users_collection,
        mock_subscription_repository,
        mock_plan_repository,
        mock_dodo_client,
    ):
        """Dodo's documented test card is a US Visa; on the Indian rail it is
        declined, so a developer could not pay with the card the docs name."""
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        checkout_response = MagicMock()
        checkout_response.session_id = "sess_003"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_003"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=checkout_response)
        mock_plan_repository.list_plans = AsyncMock(return_value=[])

        with patch.object(payment_service_module.settings, "ENV", "development"):
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID, product_id="prod_abc123"
            )
        dev_kwargs = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert dev_kwargs["billing_address"] == {
            "country": "US",
            "street": "548 Market St",
            "city": "San Francisco",
            "state": "CA",
            "zipcode": "94104",
        }
        assert dev_kwargs["customer"]["phone_number"] == "+14155550123"
        assert dev_kwargs["show_saved_payment_methods"] is True

        with patch.object(payment_service_module.settings, "ENV", "production"):
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID, product_id="prod_abc123"
            )
        prod_kwargs = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert "billing_address" not in prod_kwargs
        assert "phone_number" not in prod_kwargs["customer"]
        assert "show_saved_payment_methods" not in prod_kwargs

    async def test_return_url_follows_the_requested_path(
        self,
        payment_service,
        mock_users_collection,
        mock_subscription_repository,
        mock_plan_repository,
        mock_dodo_client,
    ):
        """A checkout started in the onboarding wizard comes back to the wizard,
        not to the standalone result page: the wizard confirms the payment in
        place and is the one screen the user sees after paying."""
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
            return_path=CheckoutSource.ONBOARDING.return_path,
        )
        call_kwargs = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert call_kwargs["return_url"].endswith("/onboarding?checkout=returned")

        await payment_service.create_subscription(user_id=FAKE_USER_ID, product_id="prod_abc123")
        call_kwargs = mock_dodo_client.checkout_sessions.create.call_args[1]
        assert call_kwargs["return_url"].endswith("/payment/success")

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

    @pytest.mark.usefixtures("mock_redis_cache", "mock_checkout_session_repository")
    async def test_stamps_the_wide_event_as_an_initiated_subscription_create(
        self,
        payment_service,
        mock_users_collection,
        mock_subscription_repository,
        mock_plan_repository,
        mock_dodo_client,
    ):
        """The payment context on the request's wide event is how a failed
        mint is found in the logs; it is set before Dodo is called."""
        _set_user(mock_users_collection, SAMPLE_USER_DOC)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        checkout_response = MagicMock()
        checkout_response.session_id = "sess_001"
        checkout_response.checkout_url = "https://checkout.dodo.dev/sess_001"
        mock_dodo_client.checkout_sessions.create = MagicMock(return_value=checkout_response)
        mock_plan_repository.list_plans = AsyncMock(return_value=[])

        with patch("app.services.payments.payment_service.log") as mock_log:
            await payment_service.create_subscription(
                user_id=FAKE_USER_ID, product_id="prod_abc123"
            )

        mock_log.set.assert_any_call(
            payment={"event_type": "create_subscription", "status": "initiated"}
        )


@pytest.mark.unit
class TestCancelSubscription:
    """Tests for DodoPaymentService.cancel_subscription."""

    async def test_records_the_cancel_through_the_reducer_as_scheduled(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_repository,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Dodo is asked for a period-end cancel, and the local row is written
        by the same reducer the webhook uses — as a scheduled cancel whatever
        status Dodo echoes back (``test_subscription_events.py`` pins that the
        reducer keeps the user on Pro until ``subscription.expired``)."""
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_dodo_client.subscriptions = MagicMock()
        # Dodo echoing the pre-update flag: the event still records the
        # scheduled cancel that was asked for, not what the echo says.
        mock_dodo_client.subscriptions.update = MagicMock(
            return_value=self._dodo_subscription(status="cancelled", scheduled=False)
        )
        applied = SubscriptionEventResult(SubscriptionEventOutcome.APPLIED, FAKE_USER_ID)

        with patch(
            f"{SERVICE_MODULE}.apply_subscription_event", AsyncMock(return_value=applied)
        ) as apply_event:
            before = datetime.now(UTC)
            result = await payment_service.cancel_subscription(FAKE_USER_ID)
            after = datetime.now(UTC)

        assert mock_dodo_client.subscriptions.update.call_args == call(
            "sub_xyz789", cancel_at_next_billing_date=True
        )
        event = apply_event.await_args.args[0]
        assert event.kind is SubscriptionEventKind.CANCELLED
        assert event.data.subscription_id == "sub_xyz789"
        assert event.data.cancel_at_next_billing_date is True
        assert event.data.cancelled_at == "2025-06-15T00:00:00Z"
        # Ordered against Dodo's own event clock, so it must be a real UTC
        # instant of now — not None, not naive.
        assert event.occurred_at.tzinfo is UTC
        assert before <= event.occurred_at <= after
        assert isinstance(result, UserSubscriptionStatus)

    async def test_a_cancel_with_no_local_row_fails_loud(
        self,
        payment_service,
        mock_subscription_repository,
        mock_dodo_client,
    ):
        """Dodo accepted the cancellation; surfacing success while nothing
        local recorded it would leave the user's status stale for good."""
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_dodo_client.subscriptions = MagicMock()
        mock_dodo_client.subscriptions.update = MagicMock(
            return_value=self._dodo_subscription(status="active")
        )
        unmatched = SubscriptionEventResult(SubscriptionEventOutcome.NO_ROW, None)

        with (
            patch(f"{SERVICE_MODULE}.apply_subscription_event", AsyncMock(return_value=unmatched)),
            pytest.raises(HTTPException) as exc_info,
        ):
            await payment_service.cancel_subscription(FAKE_USER_ID)

        assert exc_info.value.status_code == 502

    @staticmethod
    def _dodo_subscription(status: str, scheduled: bool = True) -> Subscription:
        return Subscription.model_validate(
            {
                "subscription_id": "sub_xyz789",
                "product_id": "prod_abc123",
                "status": status,
                "quantity": 1,
                "currency": "USD",
                "recurring_pre_tax_amount": 999,
                "payment_frequency_count": 1,
                "payment_frequency_interval": "Month",
                "subscription_period_count": 1,
                "subscription_period_interval": "Month",
                "next_billing_date": datetime(2025, 7, 1, tzinfo=UTC),
                "previous_billing_date": datetime(2025, 6, 1, tzinfo=UTC),
                "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                "cancelled_at": datetime(2025, 6, 15, tzinfo=UTC),
                "metadata": {"user_id": FAKE_USER_ID},
                "customer": {"customer_id": "cus_1", "email": FAKE_EMAIL, "name": "Alice"},
                "billing": {"country": "US"},
                "addons": [],
                "meters": [],
                "cancel_at_next_billing_date": scheduled,
                "on_demand": False,
                "tax_inclusive": False,
                "trial_period_days": 0,
            }
        )

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


class TestGetCachedPlanType:
    """The single read the whole paywall decides on."""

    async def test_a_cached_tier_says_it_came_from_the_cache(
        self, payment_service, mock_redis_cache
    ):
        """A stale cached FREE and a genuinely free user are indistinguishable
        downstream, so the source is the first thing an incident needs."""
        mock_redis_cache.get = AsyncMock(return_value={"plan_type": PlanType.PRO.value})

        async with captured_wide_event() as event:
            plan = await payment_service.get_cached_plan_type(FAKE_USER_ID)

        assert plan is PlanType.PRO
        assert event["payment"] == {"plan_type": "pro", "plan_source": "cache"}

    async def test_a_freshly_read_tier_says_it_came_from_the_subscription(
        self, payment_service, mock_redis_cache, mock_subscription_repository
    ):
        mock_redis_cache.get = AsyncMock(return_value=None)
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )

        async with captured_wide_event() as event:
            plan = await payment_service.get_cached_plan_type(FAKE_USER_ID)

        assert plan is PlanType.PRO
        assert event["payment"]["plan_source"] == "subscription"
        assert event["payment"]["plan_type"] == "pro"


@pytest.mark.unit
@pytest.mark.usefixtures("mock_redis_cache")
class TestVerifyPaymentCompletion:
    """Tests for DodoPaymentService.verify_payment_completion.

    Redis is stubbed for the whole class: the checkout scan caches its miss,
    and a real local Redis would carry one test's miss into the next.
    """

    @pytest.fixture
    def activation_seams(self, mock_subscription_repository, mock_users_collection):
        """The row is written by ``subscription_events``, so verification's
        recovery runs through that module's seams.

        The same repository and user mocks stand behind both modules: the test
        is one story about one user, and two mocks for one collection would let
        the two halves disagree without failing.
        """
        with (
            patch(f"{ACTIVATION_MODULE}.subscription_repository", mock_subscription_repository),
            patch(f"{ACTIVATION_MODULE}.user_repository", mock_users_collection),
            patch(f"{ACTIVATION_MODULE}.invalidate_plan_cache", new_callable=AsyncMock),
            patch(f"{ACTIVATION_MODULE}.reactivate_workflows_safely", new_callable=AsyncMock),
            patch(
                f"{ACTIVATION_MODULE}.send_pro_subscription_email", new_callable=AsyncMock
            ) as send_email,
            patch(f"{ACTIVATION_MODULE}.track_subscription_event") as track_activation,
        ):
            yield SimpleNamespace(send_email=send_email, track_activation=track_activation)

    @pytest.fixture
    def materialize_mocks(
        self,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
        mock_users_collection,
        mock_plan_cache_invalidation,
        activation_seams,
    ):
        """Every seam the Dodo materialization path touches, as one bundle."""
        return SimpleNamespace(
            subscriptions=mock_subscription_repository,
            checkouts=mock_checkout_session_repository,
            dodo=mock_dodo_client,
            users=mock_users_collection,
            send_email=activation_seams.send_email,
            track_activation=activation_seams.track_activation,
            drop_plan_cache=mock_plan_cache_invalidation,
        )

    @staticmethod
    def _dodo_subscription(
        user_id: str | None = FAKE_USER_ID,
        status: str = "active",
    ) -> Subscription:
        """The Dodo SDK's own ``Subscription``, not a stand-in for it.

        Verification revalidates whatever the SDK hands back into
        ``DodoSubscriptionData`` before anything is written, so the fixture has
        to be the real shape: a namespace or a MagicMock would answer any
        attribute and let a drift between the two schemas pass unnoticed.
        """
        return Subscription.model_validate(
            {
                "subscription_id": "sub_from_checkout",
                "product_id": "prod_abc123",
                "status": status,
                "quantity": 1,
                "currency": "USD",
                "recurring_pre_tax_amount": 30000,
                "payment_frequency_count": 1,
                "payment_frequency_interval": "Year",
                "subscription_period_count": 1,
                "subscription_period_interval": "Year",
                "next_billing_date": datetime(2027, 8, 24, tzinfo=UTC),
                "previous_billing_date": datetime(2026, 8, 24, tzinfo=UTC),
                "created_at": datetime(2026, 8, 24, tzinfo=UTC),
                "metadata": {"user_id": user_id} if user_id is not None else {},
                "customer": {"customer_id": "cus_1", "email": FAKE_EMAIL, "name": "Alice"},
                "billing": {
                    "country": "US",
                    "city": "NYC",
                    "state": "NY",
                    "street": "1 Main St",
                    "zipcode": "10001",
                },
                "addons": [],
                "meters": [],
                "cancel_at_next_billing_date": False,
                "on_demand": False,
                "tax_inclusive": False,
                "trial_period_days": 0,
            }
        )

    @staticmethod
    def _exact_retrieve(expected_id: str, result: object) -> MagicMock:
        """A ``retrieve`` stub that answers only its own id.

        Any other argument raises, so a mutant that rewrites which id gets
        passed dies in every test that walks the chain.
        """

        def impl(resource_id: str) -> object:
            if resource_id != expected_id:
                raise AssertionError(
                    f"retrieve called with {resource_id!r}, expected {expected_id!r}"
                )
            return result

        return MagicMock(side_effect=impl)

    @staticmethod
    def _wire_dodo_checkout_chain(
        mock_dodo_client,
        user_id: str | None,
        payment_id: str | None = "pay_123",
        payment_status: str | None = "succeeded",
        subscription_id: str | None = "sub_from_checkout",
        subscription_status: str = "active",
    ) -> SimpleNamespace:
        """checkout_sessions.retrieve -> payments.retrieve -> subscriptions.retrieve,
        each answering only the id the previous hop produced."""
        checkout_status = SimpleNamespace(payment_id=payment_id, payment_status=payment_status)
        payment = SimpleNamespace(subscription_id=subscription_id)
        subscription = TestVerifyPaymentCompletion._dodo_subscription(
            user_id, status=subscription_status
        )
        mock_dodo_client.checkout_sessions = SimpleNamespace(
            retrieve=TestVerifyPaymentCompletion._exact_retrieve("ches_123", checkout_status)
        )
        mock_dodo_client.payments = SimpleNamespace(
            retrieve=TestVerifyPaymentCompletion._exact_retrieve("pay_123", payment)
        )
        mock_dodo_client.subscriptions = SimpleNamespace(
            retrieve=TestVerifyPaymentCompletion._exact_retrieve("sub_from_checkout", subscription)
        )
        return subscription

    @staticmethod
    def _pending_checkout() -> SimpleNamespace:
        return SimpleNamespace(session_id="ches_123", product_id="prod_abc123")

    async def test_active_subscription_returns_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_cache_invalidation,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is True
        assert result.subscription_id == "sub_xyz789"

    async def test_an_already_recorded_subscription_still_drops_the_cached_tier(
        self,
        payment_service,
        mock_subscription_repository,
        mock_plan_cache_invalidation,
    ):
        """A request 402'd from the paywall page re-caches the free tier for
        five minutes, and it can land just after the webhook activated the
        user. Answering "payment completed" while that key stands is how a
        paid user is locked out of what they just bought."""
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            return_value=SAMPLE_SUBSCRIPTION
        )

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is True
        mock_plan_cache_invalidation.assert_awaited_once_with(FAKE_USER_ID)

    async def test_materializes_subscription_from_dodo_when_webhook_not_landed(
        self,
        payment_service,
        materialize_mocks,
    ):
        """The webhook-vs-redirect race: no local row yet, but Dodo reports the
        checkout as paid+active — materialize it and return completed."""
        materialize_mocks.subscriptions.get_active_for_user = AsyncMock(return_value=None)
        materialize_mocks.subscriptions.get_by_dodo_id = AsyncMock(return_value=None)
        created = SubscriptionDocument.model_validate(
            {**SAMPLE_SUBSCRIPTION_DOC, "dodo_subscription_id": "sub_from_checkout"}
        )
        # No row until the activation writes one; the second read is the
        # read-back that answers the caller.
        materialize_mocks.subscriptions.get_latest_active_for_user = AsyncMock(
            side_effect=[None, created]
        )
        materialize_mocks.subscriptions.create = AsyncMock(return_value=created)
        materialize_mocks.checkouts.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        self._wire_dodo_checkout_chain(materialize_mocks.dodo, FAKE_USER_ID)
        _set_user(materialize_mocks.users, SAMPLE_USER_DOC)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is True
        assert result.subscription_id == "sub_from_checkout"
        materialize_mocks.checkouts.list_recent_for_user.assert_awaited_once_with(
            FAKE_USER_ID, limit=CHECKOUT_SESSION_SCAN_LIMIT
        )
        materialize_mocks.subscriptions.get_by_dodo_id.assert_awaited_once_with("sub_from_checkout")
        # A user who just paid is refused by the gate until the cached tier is
        # dropped, and the workflows paused when they lapsed only come back
        # here — both belong to the activation the write now runs through.
        materialize_mocks.drop_plan_cache.assert_awaited_once_with(FAKE_USER_ID)
        # The materialized row must carry the Dodo subscription verbatim — a
        # drifted field here prints a wrong receipt.
        doc = materialize_mocks.subscriptions.create.call_args.args[0]
        assert doc.dodo_subscription_id == "sub_from_checkout"
        assert doc.user_id == FAKE_USER_ID
        assert doc.product_id == "prod_abc123"
        assert doc.status == "active"
        assert doc.quantity == 1
        assert doc.currency == "USD"
        assert doc.recurring_pre_tax_amount == 30000
        assert doc.payment_frequency_count == 1
        assert doc.payment_frequency_interval == "Year"
        assert doc.subscription_period_count == 1
        assert doc.subscription_period_interval == "Year"
        assert doc.next_billing_date == "2027-08-24T00:00:00Z"
        assert doc.previous_billing_date == "2026-08-24T00:00:00Z"
        assert doc.metadata == {"user_id": FAKE_USER_ID}
        assert doc.created_at is not None
        assert doc.created_at.tzinfo is not None
        assert doc.updated_at == doc.created_at
        materialize_mocks.track_activation.assert_called_once_with(
            user_id=FAKE_USER_ID,
            event_type=AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
            subscription_id="sub_from_checkout",
            plan=SubscriptionPlan(name="Pro", amount=300.0, currency="USD"),
        )
        materialize_mocks.send_email.assert_awaited_once()

    async def test_materialization_is_idempotent_with_webhook_row(
        self,
        payment_service,
        materialize_mocks,
    ):
        """If the webhook landed while we were asking Dodo, its row wins and
        nothing new is created."""
        materialize_mocks.subscriptions.get_active_for_user = AsyncMock(return_value=None)
        materialize_mocks.subscriptions.get_latest_active_for_user = AsyncMock(return_value=None)
        existing = SubscriptionDocument.model_validate(SAMPLE_SUBSCRIPTION_DOC)
        # The row the racing webhook wrote is invisible to the first read and
        # present on the read-back, which is the race this covers.
        materialize_mocks.subscriptions.get_latest_active_for_user = AsyncMock(
            side_effect=[None, existing]
        )
        materialize_mocks.subscriptions.get_by_dodo_id = AsyncMock(return_value=existing)
        materialize_mocks.subscriptions.create = AsyncMock()
        materialize_mocks.checkouts.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        self._wire_dodo_checkout_chain(materialize_mocks.dodo, FAKE_USER_ID)
        _set_user(materialize_mocks.users, SAMPLE_USER_DOC)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is True
        materialize_mocks.subscriptions.get_by_dodo_id.assert_awaited_once_with("sub_from_checkout")
        materialize_mocks.subscriptions.create.assert_not_called()
        materialize_mocks.track_activation.assert_not_called()

    async def test_no_pending_checkout_returns_not_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False

    async def test_unpaid_checkout_returns_not_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
    ):
        """Checkout still at the details-collection stage — no payment yet."""
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        # Everything downstream is valid, so a mutant that drops the
        # payment-status guard would happily materialize — and get caught.
        self._wire_dodo_checkout_chain(mock_dodo_client, FAKE_USER_ID, payment_id=None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False
        mock_dodo_client.payments.retrieve.assert_not_called()

    @staticmethod
    def _memory_cache(mock_redis_cache) -> dict[str, object]:
        """A dict-backed Redis, so a second verify sees what the first cached."""
        store: dict[str, object] = {}

        async def _get(key: str, model: object = None) -> object:
            return store.get(key)

        async def _set(key: str, value: object, ttl: int = 0, model: object = None) -> bool:
            store[key] = value
            return True

        async def _delete(key: str) -> None:
            store.pop(key, None)

        mock_redis_cache.get = AsyncMock(side_effect=_get)
        mock_redis_cache.set = AsyncMock(side_effect=_set)
        mock_redis_cache.delete = AsyncMock(side_effect=_delete)
        return store

    async def test_a_reconciled_subscription_reaches_the_reducer_as_an_activation_stamped_now(
        self,
        payment_service,
        mock_subscription_repository,
        mock_dodo_client,
        mock_plan_cache_invalidation,
    ):
        """A recovery has no Dodo event timestamp; the reducer orders it by the
        moment Dodo answered, which must be a real UTC instant — a None or a
        naive one would compare wrong against the webhook's."""
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(
            side_effect=[None, SAMPLE_SUBSCRIPTION]
        )
        mock_dodo_client.subscriptions = SimpleNamespace(
            retrieve=self._exact_retrieve("sub_from_checkout", self._dodo_subscription())
        )
        applied = SubscriptionEventResult(SubscriptionEventOutcome.CREATED, FAKE_USER_ID)

        with patch(
            f"{SERVICE_MODULE}.apply_subscription_event", AsyncMock(return_value=applied)
        ) as apply_event:
            before = datetime.now(UTC)
            result = await payment_service.verify_payment_completion(
                FAKE_USER_ID, subscription_id="sub_from_checkout"
            )
            after = datetime.now(UTC)

        assert result.payment_completed is True
        event = apply_event.await_args.args[0]
        assert event.kind is SubscriptionEventKind.ACTIVATED
        assert event.data.subscription_id == "sub_from_checkout"
        assert event.occurred_at.tzinfo is UTC
        assert before <= event.occurred_at <= after

    async def test_an_unpaid_scan_runs_once_across_the_web_clients_retries(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
        mock_redis_cache,
    ):
        """The result page verifies eight times over ~50 s
        (``verifyPaymentWithRetry.ts``). Every retry re-scanned every recorded
        session against Dodo — up to CHECKOUT_SESSION_SCAN_LIMIT round trips
        per verify, eight times, for an answer that had not changed. The
        negative result is cached for the retry window so the scan costs one
        pass, and the eight verifies read the row (which the webhook may have
        created meanwhile) before ever asking Dodo again."""
        store = self._memory_cache(mock_redis_cache)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        sessions = [
            SimpleNamespace(session_id=f"ches_{i}", product_id="prod_abc123") for i in range(3)
        ]
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(return_value=sessions)
        unpaid = SimpleNamespace(payment_id=None, payment_status=None)
        mock_dodo_client.checkout_sessions = SimpleNamespace(
            retrieve=MagicMock(return_value=unpaid)
        )

        async with captured_wide_event() as event:
            result = await payment_service.verify_payment_completion(FAKE_USER_ID)
        assert result.payment_completed is False
        assert event["payment"] == {"checkout_scan": "miss"}
        for _ in range(7):
            async with captured_wide_event() as event:
                result = await payment_service.verify_payment_completion(FAKE_USER_ID)
            assert result.payment_completed is False
            # The skipped scan is on the record, under the payment namespace
            # every other billing field lives in — a verify that never asked
            # Dodo is otherwise indistinguishable from one that did.
            assert event["payment"] == {"checkout_scan": "cached_miss"}

        assert mock_dodo_client.checkout_sessions.retrieve.call_count == len(sessions)
        mock_redis_cache.set.assert_awaited_once_with(
            f"{CHECKOUT_SCAN_MISS_CACHE_PREFIX}{FAKE_USER_ID}", True, ttl=CHECKOUT_SCAN_MISS_TTL
        )
        assert f"{CHECKOUT_SCAN_MISS_CACHE_PREFIX}{FAKE_USER_ID}" in store

    async def test_a_session_dodo_could_not_answer_for_is_not_cached_as_unpaid(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
        mock_redis_cache,
    ):
        """A Dodo outage during the scan is transient; caching it as "not paid"
        would hide a paid session from every retry in the window."""
        self._memory_cache(mock_redis_cache)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        mock_dodo_client.checkout_sessions = SimpleNamespace(
            retrieve=MagicMock(side_effect=RuntimeError("Dodo API down"))
        )

        async with captured_wide_event() as event:
            await payment_service.verify_payment_completion(FAKE_USER_ID)
        await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert mock_dodo_client.checkout_sessions.retrieve.call_count == 2
        mock_redis_cache.set.assert_not_awaited()
        assert event["payment"] == {"checkout_scan": "inconclusive"}

    async def test_a_paid_session_whose_subscription_is_not_yet_active_is_asked_again(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
        mock_redis_cache,
    ):
        """Paid but Dodo has not flipped the subscription to active yet: the
        next retry is exactly the one that should find it active."""
        self._memory_cache(mock_redis_cache)
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        self._wire_dodo_checkout_chain(
            mock_dodo_client, FAKE_USER_ID, subscription_status="pending"
        )

        async with captured_wide_event() as event:
            await payment_service.verify_payment_completion(FAKE_USER_ID)
        await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert mock_dodo_client.subscriptions.retrieve.call_count == 2
        mock_redis_cache.set.assert_not_awaited()
        assert event["payment"]["checkout_scan"] == "inconclusive"

    async def test_settled_payment_not_succeeded_returns_not_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
    ):
        """A payment id exists but the payment has not succeeded yet."""
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        self._wire_dodo_checkout_chain(mock_dodo_client, FAKE_USER_ID, payment_status="processing")

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False
        mock_dodo_client.payments.retrieve.assert_not_called()

    async def test_payment_without_subscription_returns_not_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
    ):
        """A settled one-off payment with no subscription behind it."""
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        self._wire_dodo_checkout_chain(mock_dodo_client, FAKE_USER_ID, subscription_id=None)
        # A payment payload may not carry the field at all — the defensive
        # getattr default makes that the quiet "no subscription" path, not an
        # AttributeError swallowed into the Dodo-failure warning.
        mock_dodo_client.payments = SimpleNamespace(
            retrieve=self._exact_retrieve("pay_123", SimpleNamespace())
        )

        with patch("app.services.payments.payment_service.log") as mock_log:
            result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False
        mock_log.warning.assert_not_called()
        mock_dodo_client.subscriptions.retrieve.assert_not_called()

    async def test_inactive_dodo_subscription_returns_not_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
    ):
        """Dodo answers, but the subscription never went active (e.g. on_hold)."""
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        mock_subscription_repository.create = AsyncMock()
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        self._wire_dodo_checkout_chain(
            mock_dodo_client, FAKE_USER_ID, subscription_status="on_hold"
        )

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False
        mock_subscription_repository.create.assert_not_called()

    async def test_materializes_when_metadata_has_no_user_id(
        self,
        payment_service,
        materialize_mocks,
    ):
        """Metadata without a user id falls back to the customer email, the
        same rule the webhook resolves ownership by — Dodo was given this
        user's own address when the checkout was minted."""
        materialize_mocks.subscriptions.get_active_for_user = AsyncMock(return_value=None)
        materialize_mocks.subscriptions.get_by_dodo_id = AsyncMock(return_value=None)
        created = SubscriptionDocument.model_validate(
            {**SAMPLE_SUBSCRIPTION_DOC, "dodo_subscription_id": "sub_from_checkout"}
        )
        # No row until the activation writes one; the second read is the
        # read-back that answers the caller.
        materialize_mocks.subscriptions.get_latest_active_for_user = AsyncMock(
            side_effect=[None, created]
        )
        materialize_mocks.subscriptions.create = AsyncMock(return_value=created)
        materialize_mocks.checkouts.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        self._wire_dodo_checkout_chain(materialize_mocks.dodo, None)
        _set_user(materialize_mocks.users, SAMPLE_USER_DOC)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is True
        assert materialize_mocks.subscriptions.create.call_args.args[0].user_id == FAKE_USER_ID
        materialize_mocks.users.get_by_email.assert_awaited_with(FAKE_EMAIL)

    async def test_ignores_subscription_owned_by_other_user(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
    ):
        """Metadata naming someone else means the subscription is not this
        user's, whatever their checkout session says."""
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        mock_subscription_repository.create = AsyncMock()
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        self._wire_dodo_checkout_chain(mock_dodo_client, OTHER_USER_ID)

        async with captured_wide_event() as event:
            result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False
        mock_subscription_repository.create.assert_not_called()
        # Handing a subscription to a stranger is what the audit trail exists
        # for, and both recovery routes refuse it the same way.
        assert event["audit"] == [
            {
                "msg": "payment verification refused",
                "actor": FAKE_USER_ID,
                "provider": "dodo",
                "reason": "subscription_owner_mismatch",
            }
        ]

    async def test_dodo_api_failure_returns_not_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
        mock_dodo_client,
    ):
        """The fallback is best-effort — Dodo being down must not 500 verify."""
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)
        mock_checkout_session_repository.list_recent_for_user = AsyncMock(
            return_value=[self._pending_checkout()]
        )
        mock_dodo_client.checkout_sessions = MagicMock()
        mock_dodo_client.checkout_sessions.retrieve = MagicMock(
            side_effect=Exception("Dodo API down")
        )

        with patch("app.services.payments.payment_service.log") as mock_log:
            result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False
        mock_log.warning.assert_called_once_with(
            f"{LogTag.PAYMENT} Failed to resolve checkout with Dodo during verify",
            error="Dodo API down",
            error_type="Exception",
            user_id=FAKE_USER_ID,
            session_id="ches_123",
        )

    async def test_no_subscription_returns_not_completed(
        self,
        payment_service,
        mock_subscription_repository,
        mock_checkout_session_repository,
    ):
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.get_latest_active_for_user = AsyncMock(return_value=None)

        result = await payment_service.verify_payment_completion(FAKE_USER_ID)

        assert result.payment_completed is False
        assert "No active subscription" in result.message


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
        assert status.has_ever_subscribed is False

    async def test_lapsed_user_is_distinguishable_from_a_never_paid_one(
        self,
        payment_service,
        mock_subscription_repository,
    ):
        """No active subscription but a row in history — the paywall shows the
        "your subscription ended" copy off this flag, so it must not read the
        same as a user who has never paid."""
        mock_subscription_repository.get_active_for_user = AsyncMock(return_value=None)
        mock_subscription_repository.has_any_for_user = AsyncMock(return_value=True)

        status = await payment_service.get_user_subscription_status(FAKE_USER_ID)

        assert status.is_subscribed is False
        assert status.has_ever_subscribed is True
        # Scoped to this user: an unscoped history read would show the "your
        # subscription ended" copy to everyone the moment anyone had ever paid.
        mock_subscription_repository.has_any_for_user.assert_awaited_once_with(FAKE_USER_ID)

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
        assert status.has_ever_subscribed is True
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

    async def test_mints_for_this_user_with_the_resolved_product_and_return_path(
        self,
        payment_service,
        mock_plan_repository,
        mock_subscription_repository,
        mock_users_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        mint = AsyncMock(
            return_value=CreateSubscriptionResponse(
                subscription_id="cs_1",
                payment_link="https://checkout.dodopayments.com/s/cs_1",
                status="payment_link_created",
            )
        )
        with patch.object(payment_service, "create_subscription", mint):
            await payment_service.create_pro_checkout(FAKE_USER_ID, PlanDuration.YEARLY)

        # The checkout session must be created for THIS user, tied by metadata.
        mint.assert_awaited_once_with(
            FAKE_USER_ID, "prod_y", discount_code=None, return_path="/payment/success"
        )

    async def test_configured_paywall_discount_is_pre_applied_to_the_minted_session(
        self,
        payment_service,
        mock_plan_repository,
        mock_subscription_repository,
        mock_users_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Every surface advertises ``PAYWALL_DISCOUNT_CODE``; the one place the
        session is minted must apply it, or the link and the pitch drift."""
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        mint = AsyncMock(
            return_value=CreateSubscriptionResponse(
                subscription_id="cs_1",
                payment_link="https://checkout.dodopayments.com/s/cs_1",
                status="payment_link_created",
            )
        )
        with (
            patch("app.services.payments.payment_service.settings") as mock_settings,
            patch.object(payment_service, "create_subscription", mint),
        ):
            mock_settings.PAYWALL_DISCOUNT_CODE = "SAVE20"
            await payment_service.create_pro_checkout(FAKE_USER_ID)

        assert mint.await_args.kwargs["discount_code"] == "SAVE20"

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

    async def test_every_call_mints_a_fresh_session(
        self,
        payment_service,
        mock_plan_repository,
        mock_subscription_repository,
        mock_users_collection,
        mock_redis_cache,
        mock_dodo_client,
    ):
        """Dodo sessions are single-use: after a declined card the old one only
        renders "link expired". Handing a remembered session back stranded the
        user on that page (seen live on the dev drive), so nothing is remembered."""
        mock_plan_repository.list_plans = AsyncMock(return_value=CATALOGUE)
        sessions = []
        for sid in ("cs_1", "cs_2"):
            session = MagicMock()
            session.session_id = sid
            session.checkout_url = f"https://checkout.dodopayments.com/s/{sid}"
            sessions.append(session)
        mock_dodo_client.checkout_sessions.create = MagicMock(side_effect=sessions)

        first = await payment_service.create_pro_checkout(FAKE_USER_ID)
        second = await payment_service.create_pro_checkout(FAKE_USER_ID)

        assert (first.checkout.subscription_id, second.checkout.subscription_id) == ("cs_1", "cs_2")
        assert mock_dodo_client.checkout_sessions.create.call_count == 2
        assert not [
            c for c in mock_redis_cache.set.await_args_list if c.args[0].startswith("upgrade_link:")
        ]


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
