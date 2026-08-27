"""
Payment and subscription related models for Dodo Payments integration.
"""

from datetime import datetime
from enum import Enum, StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import MongoDocument


class PlanType(str, Enum):
    """Subscription plan types."""

    FREE = "free"
    PRO = "pro"


class PlanDuration(StrEnum):
    """Billing cycle a plan is charged on.

    Closed and repository-owned: the catalogue is written by
    ``scripts/payment_setup.py`` and the web already types the wire field as
    ``"monthly" | "yearly"`` (``apps/web/src/features/pricing/api/pricingApi.ts``).
    """

    MONTHLY = "monthly"
    YEARLY = "yearly"


class SubscriptionStatus(str, Enum):
    """Subscription status with clear definitions."""

    PENDING = "pending"  # Payment link created, waiting for payment
    ACTIVE = "active"  # Active with successful payment
    ON_HOLD = "on_hold"  # Temporarily paused
    CANCELLED = "cancelled"  # Cancelled by user or system
    FAILED = "failed"  # Payment failed
    EXPIRED = "expired"  # Expired subscription


# Request Models
class CreateSubscriptionRequest(BaseModel):
    """Simplified request model for creating a subscription - backend handles security."""

    product_id: str = Field(..., description="Product ID to subscribe to")
    quantity: int = Field(1, description="Quantity of subscriptions")
    discount_code: str | None = Field(
        None, description="Discount code pre-applied on the hosted checkout page"
    )


# Response Models
class PlanResponse(BaseModel):
    """Response model for subscription plan."""

    id: str = Field(..., description="Plan ID")
    dodo_product_id: str = Field(..., description="Dodo product ID")
    name: str = Field(..., description="Plan name")
    description: str | None = Field(None, description="Plan description")
    amount: int = Field(..., description="Plan amount")
    currency: str = Field(..., description="Currency")
    duration: PlanDuration = Field(..., description="Billing duration")
    max_users: int | None = Field(None, description="Maximum users")
    features: list[str] = Field(default_factory=list, description="Features")
    is_active: bool = Field(..., description="Active status")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")


class CreateSubscriptionResponse(BaseModel):
    """Hosted-checkout session created for a new subscription."""

    # Dodo's checkout-session id, not a subscription id — the subscription only exists
    # once the `subscription.active` webhook arrives. Field name is the wire contract
    # the frontend already reads (apps/web/src/features/pricing/api/pricingApi.ts).
    subscription_id: str = Field(..., description="Dodo checkout session ID")
    payment_link: str | None = Field(None, description="Hosted checkout URL")
    status: str = Field(..., description="Checkout creation status")


class ProCheckout(BaseModel):
    """A resolved Pro plan paired with its hosted checkout session.

    One catalogue resolution backs both, so the price quoted to the user and the
    price behind the link can never disagree — including when the session comes
    from cache and was minted under an earlier catalogue read.
    """

    plan: PlanResponse
    checkout: CreateSubscriptionResponse


class UserSubscriptionStatus(BaseModel):
    """Response model for user subscription status."""

    user_id: str = Field(..., description="User ID")
    current_plan: dict[str, Any] | None = Field(None, description="Current plan details")
    subscription: dict[str, Any] | None = Field(None, description="Current subscription")
    is_subscribed: bool = Field(False, description="Whether user has an active subscription")
    days_remaining: int | None = Field(None, description="Days remaining in current period")
    can_upgrade: bool = Field(True, description="Whether user can upgrade")
    can_downgrade: bool = Field(True, description="Whether user can downgrade")

    has_subscription: bool | None = Field(None, description="Legacy field - use is_subscribed")
    plan_type: PlanType | None = Field(None, description="Legacy field - check current_plan")
    status: SubscriptionStatus | None = Field(None, description="Legacy field - check subscription")


# Database Models (Internal)
class PlanDocument(MongoDocument):
    """A subscription plan as stored in the ``subscription_plans`` collection.

    Global (not user-scoped); ``id`` is the stringified Mongo ``_id``. Seeded by
    scripts and read-only in the app, so the base never stamps its timestamps.
    """

    model_config = ConfigDict(extra="ignore")

    dodo_product_id: str | None = None
    name: str
    description: str | None = None
    amount: int
    currency: str
    duration: PlanDuration
    max_users: int | None = None
    features: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class PlanUpdate(BaseModel):
    """Typed ``$set`` fields for a plan row (admin/seed edits)."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None


class SubscriptionDocument(MongoDocument):
    """A subscription as stored in the ``subscriptions`` collection.

    Global (webhook updates key on ``dodo_subscription_id`` with no user in scope);
    ``user_id`` is a plain field. ``id`` is the stringified Mongo ``_id`` — kept so
    the status endpoint returns the same id it did before the repository.
    ``extra="allow"`` preserves the many Dodo billing fields verbatim in responses.
    """

    model_config = ConfigDict(extra="allow")

    dodo_subscription_id: str
    user_id: str
    product_id: str | None = None
    status: str = "pending"
    cancel_at_next_billing_date: bool | None = None
    #: The ISO string Dodo sends, stored verbatim (see ``SubscriptionUpdate``).
    next_billing_date: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SubscriptionUpdate(BaseModel):
    """Typed ``$set`` fields for a subscription.

    Covers every field the Dodo subscription webhooks write. Types mirror
    ``DodoSubscriptionData`` (``app/models/webhook_models.py``), which is where
    these values come from — the billing dates are the ISO **strings** Dodo
    sends and are stored verbatim, not parsed to ``datetime``.

    ``validate_assignment`` because the renewal handler sets the billing dates by
    assignment, only when the event carries them. Without it assignment neither
    validates nor coerces, so a wrong-typed value would reach Mongo's ``$set``
    unchecked — the same gap ``ReminderUpdate`` carries a flag for.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    status: str | None = None
    product_id: str | None = None
    quantity: int | None = None
    recurring_pre_tax_amount: int | None = None
    next_billing_date: str | None = None
    previous_billing_date: str | None = None
    cancelled_at: str | None = None
    cancel_at_next_billing_date: bool | None = None


class ProcessedWebhookDocument(MongoDocument):
    """An idempotency record in the ``processed_webhooks`` collection.

    Keyed by the business ``webhook_id`` (a unique index enforces
    once-only processing). ``processed_at`` carries a 30-day TTL (see indexes).
    """

    model_config = ConfigDict(extra="ignore")

    webhook_id: str
    event_type: str | None = None
    status: str | None = None
    message: str | None = None
    payment_id: str | None = None
    subscription_id: str | None = None
    processed_at: datetime | None = None


class ProcessedWebhookUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None


class PaymentVerificationResponse(BaseModel):
    payment_completed: bool
    subscription_id: str | None = None
    message: str


class PaymentHistoryEntry(BaseModel):
    """One charge from Dodo's payment ledger, flattened for display.

    Dodo is the ledger — nothing local records individual charges — so these are
    read live from ``payments.list`` rather than a collection.
    """

    payment_id: str
    status: str | None = None
    amount: int = Field(..., description="Charged amount in the currency's minor unit")
    currency: str
    created_at: datetime
    payment_method: str | None = None


class SubscriptionDetails(BaseModel):
    """Everything GAIA needs to answer 'what am I on, and what have I paid?'.

    ``UserSubscriptionStatus`` is the frontend's shape and carries raw Mongo/plan
    dicts; this is the flattened, typed view the agent reads.
    """

    plan_type: PlanType
    is_subscribed: bool
    status: SubscriptionStatus | None = None
    plan_name: str | None = None
    #: Plan price in the currency's minor unit, matching Dodo's wire format.
    amount: int | None = None
    currency: str | None = None
    billing_cycle: PlanDuration | None = None
    next_billing_date: str | None = None
    cancel_at_next_billing_date: bool = False
    payments: list[PaymentHistoryEntry] = Field(default_factory=list)
