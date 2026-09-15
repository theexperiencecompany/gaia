"""Shared fixtures and test data for the payment service test suite.

``test_payment_service.py`` covers ``DodoPaymentService``;
``test_payment_webhook_service.py`` covers ``PaymentWebhookService``. Both
need the same fake user/subscription documents, the same webhook-event
payload shape, and several webhook-processing seams — declared once here so
neither file re-declares them.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest

from app.models.payment_models import SubscriptionDocument
from app.models.user_models import UserDocument
from app.services.payments.payment_webhook_service import PaymentWebhookService

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_EMAIL = "alice@example.com"
NOW = datetime.now(UTC)

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

SAMPLE_SUBSCRIPTION = SubscriptionDocument.model_validate(
    {
        # _id holds a raw ObjectId that extra="allow" would keep and later
        # serialization could not dump — the id rides on the typed field.
        **{k: v for k, v in SAMPLE_SUBSCRIPTION_DOC.items() if k != "_id"},
        "id": str(SAMPLE_SUBSCRIPTION_DOC["_id"]),
    }
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


# ---------------------------------------------------------------------------
# Full webhook payloads
# ---------------------------------------------------------------------------

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
# Fixtures shared by DodoPaymentService and PaymentWebhookService tests
# ---------------------------------------------------------------------------

# Webhook-service fixtures --------------------------------------------------


@pytest.fixture
def mock_webhook_subscription_repository():
    """The repository behind ``subscription_events``, the one writer of rows.

    By default the subscription already exists as an active row with no
    billing dates recorded (``SAMPLE_SUBSCRIPTION``), which is what every
    lifecycle event needs to find; a test about activation creating the row
    sets ``get_by_dodo_id`` to return ``None``.
    """
    mock_repo = MagicMock()
    mock_repo.get_by_dodo_id = AsyncMock(return_value=SAMPLE_SUBSCRIPTION)
    mock_repo.create = AsyncMock()
    mock_repo.apply_update_by_dodo_id = AsyncMock(return_value=True)
    with patch("app.services.payments.subscription_events.subscription_repository", mock_repo):
        yield mock_repo


@pytest.fixture
def mock_webhook_users_collection():
    with patch("app.services.payments.subscription_events.user_repository") as mock_repo:
        _set_user(mock_repo, SAMPLE_USER_DOC)
        yield mock_repo


@pytest.fixture
def mock_processed_webhook_repository():
    with patch(
        "app.services.payments.payment_webhook_service.processed_webhook_repository"
    ) as mock_repo:
        mock_repo.claim = AsyncMock(return_value=True)
        mock_repo.record_outcome = AsyncMock()
        mock_repo.release = AsyncMock()
        yield mock_repo


@pytest.fixture
def mock_track_payment():
    with patch("app.services.payments.payment_webhook_service.track_payment_event") as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_track_subscription():
    with patch("app.services.payments.subscription_events.track_subscription_event") as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_deactivate_workflows():
    """The reducer pauses lapsed workflows through a deferred import (see
    ``mock_activation_workflow_reactivation``), so the seam is the source."""
    with patch(
        "app.services.workflow.subscription_pause.deactivate_workflows_for_lapsed_subscription",
        new_callable=AsyncMock,
    ) as mock_fn:
        mock_fn.return_value = 0
        yield mock_fn


@pytest.fixture
def mock_webhook_send_email():
    with patch(
        "app.services.payments.subscription_events.send_pro_subscription_email",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_activation_workflow_reactivation():
    """The reducer resumes lapsed workflows on activation; that reaches the
    workflow stack, which no webhook test wants to run. Patched at the source
    module because the import is deferred to break a cycle.

    Not autouse here: this conftest is shared by every file under
    ``tests/unit/services/``, so autouse would silently patch an unrelated
    workflow-pause seam for every other service's tests. The payment webhook
    module opts in via ``pytestmark = pytest.mark.usefixtures(...)``.
    """
    with patch(
        "app.services.workflow.subscription_pause.reactivate_workflows_for_restored_subscription",
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


@pytest.fixture
def webhook_side_effects_stubbed(mock_track_subscription, mock_subscription_plan_cache_drop):
    """The side effects a webhook fires that most tests only need kept in memory.

    Analytics and the plan-cache bust are requested by name where a test asserts
    on them; this bundles the pair for the tests that merely must not let them
    reach PostHog or Redis, so a signature lists what it checks rather than what
    it is avoiding.
    """
    return mock_track_subscription, mock_subscription_plan_cache_drop


@pytest.fixture
def mock_subscription_plan_cache_drop():
    """Keep the reducer's plan-cache drop out of Redis.

    Every applied subscription event drops the owner's cached tier. Not
    autouse here for the same reason as ``mock_activation_workflow_reactivation``
    above — opted into via ``pytestmark`` in the payment webhook test module.
    """
    with patch(
        "app.services.payments.subscription_events.invalidate_plan_cache", new_callable=AsyncMock
    ) as mock_fn:
        yield mock_fn
