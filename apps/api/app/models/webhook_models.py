"""
Clean webhook models for Dodo Payments based on actual webhook format.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


class DodoWebhookEventType(str, Enum):
    """Dodo Payments webhook event types."""

    # Payment events
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_PROCESSING = "payment.processing"
    PAYMENT_CANCELLED = "payment.cancelled"

    # Subscription events
    SUBSCRIPTION_ACTIVE = "subscription.active"
    SUBSCRIPTION_RENEWED = "subscription.renewed"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    SUBSCRIPTION_EXPIRED = "subscription.expired"
    SUBSCRIPTION_FAILED = "subscription.failed"
    SUBSCRIPTION_ON_HOLD = "subscription.on_hold"
    SUBSCRIPTION_PLAN_CHANGED = "subscription.plan_changed"


class DodoCustomerData(BaseModel):
    """Customer info from webhook."""

    customer_id: str
    email: str
    name: str


class DodoBillingData(BaseModel):
    """Billing address from webhook."""

    city: str
    country: str
    state: str
    street: str
    zipcode: str


class DodoPaymentData(BaseModel):
    """Payment data from payment webhook."""

    payment_id: str
    subscription_id: str | None = None
    business_id: str
    brand_id: str
    customer: DodoCustomerData
    billing: DodoBillingData
    currency: str
    total_amount: int
    settlement_amount: int
    settlement_currency: str
    tax: int
    settlement_tax: int
    status: str
    payment_method: str
    card_network: str | None = None
    card_type: str | None = None
    card_last_four: str | None = None
    card_issuing_country: str | None = None
    created_at: str
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class DodoSubscriptionData(BaseModel):
    """Subscription data from subscription webhook."""

    subscription_id: str
    product_id: str
    customer: DodoCustomerData
    billing: DodoBillingData
    status: str
    currency: str
    quantity: int
    recurring_pre_tax_amount: int
    payment_frequency_count: int
    payment_frequency_interval: str
    subscription_period_count: int
    subscription_period_interval: str
    next_billing_date: str | None = None
    previous_billing_date: str | None = None
    created_at: str
    cancelled_at: str | None = None
    cancel_at_next_billing_date: bool = False
    tax_inclusive: bool = False
    trial_period_days: int = 0
    on_demand: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    addons: list[Any] = Field(default_factory=list)
    discount_id: str | None = None


class DodoWebhookEvent(BaseModel):
    """Dodo webhook event structure."""

    business_id: str
    type: DodoWebhookEventType
    timestamp: str
    data: dict[str, Any]

    def get_payment_data(self) -> DodoPaymentData | None:
        """Extract payment data if payment event."""
        if self.type.value.startswith("payment."):
            try:
                return DodoPaymentData(**self.data)
            except ValidationError as exc:
                # Loud on purpose: returning None here is indistinguishable from
                # "not a payment event", so a provider schema change would silently
                # stop payment data reaching billing with nothing in the logs.
                log.error(
                    f"{LogTag.PAYMENT} Dodo payment webhook payload did not validate",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return None
        return None

    def get_subscription_data(self) -> DodoSubscriptionData | None:
        """Extract subscription data if subscription event."""
        if self.type.value.startswith("subscription."):
            try:
                return DodoSubscriptionData(**self.data)
            except ValidationError as exc:
                # Loud on purpose: returning None here is indistinguishable from
                # "not a subscription event", so a provider schema change would silently
                # stop subscription data reaching billing with nothing in the logs.
                log.error(
                    f"{LogTag.PAYMENT} Dodo subscription webhook payload did not validate",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return None
        return None


class DodoWebhookProcessingResult(BaseModel):
    """Result of webhook processing."""

    event_type: str
    status: str  # "processed", "ignored", "failed"
    message: str
    payment_id: str | None = None
    subscription_id: str | None = None


class DodoWebhookAckResponse(BaseModel):
    """Acknowledgement returned to Dodo once a webhook has been accepted."""

    status: Literal["success"] = "success"
    event_type: str
    processing_status: str
    message: str


class ComposioWebhookAckResponse(BaseModel):
    """Acknowledgement returned to Composio once a webhook has been accepted."""

    status: Literal["success"] = "success"
    message: str


class ComposioWebhookEvent(BaseModel):
    """Composio webhook event structure."""

    type: str
    timestamp: str
    data: dict[str, Any]
    connection_id: str
    connection_nano_id: str
    trigger_nano_id: str
    trigger_id: str
    user_id: str

    model_config = ConfigDict(extra="allow")

    @field_validator("type", mode="before")
    @classmethod
    def normalize_trigger_type(cls, v: object) -> object:
        """Convert trigger type to uppercase to match TRIGGER_TYPES definition."""
        if isinstance(v, str):
            return v.upper()
        return v


class ComposioConnectionToolkit(BaseModel):
    """Toolkit reference on a connection-lifecycle event."""

    slug: str


class ComposioConnectionAuthConfig(BaseModel):
    """Auth config reference on a connection-lifecycle event."""

    model_config = ConfigDict(extra="allow")

    id: str


class ComposioConnectionData(BaseModel):
    """``data`` of a Composio connection-lifecycle event.

    Composio delivers the raw snake_case ``SingleConnectedAccountDetailedResponse``
    (mirroring ``GET /api/v3/connected_accounts/{id}``). Only the fields GAIA acts
    on are declared; the rest — including the ``state`` blob carrying access and
    refresh tokens — is accepted and never read or logged.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    user_id: str
    status: str
    status_reason: str | None = None
    toolkit: ComposioConnectionToolkit
    auth_config: ComposioConnectionAuthConfig


class ComposioConnectionEvent(BaseModel):
    """Composio connection-lifecycle event, e.g. ``composio.connected_account.expired``.

    Deliberately separate from :class:`ComposioWebhookEvent`: connection events
    carry none of the trigger identifiers that model requires, and its ``type``
    validator uppercases the event name so it could never match the lowercase
    literal the SDK's type guards compare against. The envelope's own ``id`` and
    ``timestamp`` are optional because GAIA only logs them — a webhook-version
    drift there must not reject an event GAIA can still act on.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    data: ComposioConnectionData
    id: str | None = None
    timestamp: str | None = None
