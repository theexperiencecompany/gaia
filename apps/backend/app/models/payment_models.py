"""
Payment and subscription related models for Dodo Payments integration.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlanType(str, Enum):
    """Subscription plan types."""

    FREE = "free"
    PRO = "pro"


class PlanDuration(str, Enum):
    """Plan billing duration."""

    MONTHLY = "monthly"
    YEARLY = "yearly"


class PaymentStatus(str, Enum):
    """Payment status."""

    PENDING = "pending"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class SubscriptionStatus(str, Enum):
    """Subscription status with clear definitions."""

    PENDING = "pending"  # Payment link created, waiting for payment
    ACTIVE = "active"  # Active with successful payment
    ON_HOLD = "on_hold"  # Temporarily paused
    CANCELLED = "cancelled"  # Cancelled by user or system
    FAILED = "failed"  # Payment failed
    EXPIRED = "expired"  # Expired subscription


class Currency(str, Enum):
    """Supported currencies."""

    INR = "INR"
    USD = "USD"


# Request Models
class CreatePlanRequest(BaseModel):
    """Request model for creating a subscription plan."""

    name: str = Field(..., description="Name of the plan")
    description: Optional[str] = Field(None, description="Plan description")
    amount: int = Field(..., description="Plan amount in smallest currency unit")
    currency: Currency = Field(Currency.USD, description="Currency")
    duration: PlanDuration = Field(..., description="Billing duration")
    max_users: Optional[int] = Field(None, description="Maximum users allowed")
    features: List[str] = Field(default_factory=list, description="List of features")
    is_active: bool = Field(True, description="Whether the plan is active")


class CreateSubscriptionRequest(BaseModel):
    """Simplified request model for creating a subscription - backend handles security."""

    product_id: str = Field(..., description="Product ID to subscribe to")
    quantity: int = Field(1, description="Quantity of subscriptions")


# Response Models
class PlanResponse(BaseModel):
    """Response model for subscription plan."""

    id: str = Field(..., description="Plan ID")
    dodo_product_id: str = Field(..., description="Dodo product ID")
    name: str = Field(..., description="Plan name")
    description: Optional[str] = Field(None, description="Plan description")
    amount: int = Field(..., description="Plan amount")
    currency: str = Field(..., description="Currency")
    duration: str = Field(..., description="Billing duration")
    max_users: Optional[int] = Field(None, description="Maximum users")
    features: List[str] = Field(default_factory=list, description="Features")
    is_active: bool = Field(..., description="Active status")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")


class SubscriptionResponse(BaseModel):
    """Response model for subscription."""

    id: str = Field(..., description="Internal subscription ID")
    dodo_subscription_id: str = Field(..., description="Dodo subscription ID")
    user_id: str = Field(..., description="User ID")
    product_id: str = Field(..., description="Product ID")
    status: SubscriptionStatus = Field(..., description="Subscription status")
    quantity: int = Field(..., description="Quantity")
    payment_link: Optional[str] = Field(None, description="Payment link URL")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")


class PaymentResponse(BaseModel):
    """Response model for payment."""

    id: str = Field(..., description="Payment ID")
    user_id: str = Field(..., description="User ID")
    subscription_id: Optional[str] = Field(None, description="Subscription ID")
    amount: int = Field(..., description="Payment amount")
    currency: str = Field(..., description="Currency")
    status: PaymentStatus = Field(..., description="Payment status")
    description: Optional[str] = Field(None, description="Payment description")
    created_at: datetime = Field(..., description="Creation timestamp")


class UserSubscriptionStatus(BaseModel):
    """Response model for user subscription status."""

    user_id: str = Field(..., description="User ID")
    current_plan: Optional[Dict[str, Any]] = Field(
        None, description="Current plan details"
    )
    subscription: Optional[Dict[str, Any]] = Field(
        None, description="Current subscription"
    )
    is_subscribed: bool = Field(
        False, description="Whether user has an active subscription"
    )
    days_remaining: Optional[int] = Field(
        None, description="Days remaining in current period"
    )
    can_upgrade: bool = Field(True, description="Whether user can upgrade")
    can_downgrade: bool = Field(True, description="Whether user can downgrade")

    has_subscription: Optional[bool] = Field(
        None, description="Legacy field - use is_subscribed"
    )
    plan_type: Optional[PlanType] = Field(
        None, description="Legacy field - check current_plan"
    )
    status: Optional[SubscriptionStatus] = Field(
        None, description="Legacy field - check subscription"
    )


class PaymentHistoryResponse(BaseModel):
    """Response model for payment history."""

    payments: List[PaymentResponse] = Field(
        default_factory=list, description="Payment list"
    )
    total_count: int = Field(0, description="Total payments")
    total_amount: int = Field(0, description="Total amount paid")


class WebhookEvent(BaseModel):
    """Webhook event model for Dodo Payments."""

    addons: List[Dict[str, Any]] = Field(default_factory=list, description="Addons")
    billing: Dict[str, Any] = Field(..., description="Billing address")
    cancel_at_next_billing_date: bool = Field(..., description="Cancel at next billing")
    created_at: str = Field(..., description="Creation timestamp")
    currency: str = Field(..., description="Currency")
    customer: Dict[str, Any] = Field(..., description="Customer details")
    metadata: Dict[str, Any] = Field(..., description="Metadata")
    next_billing_date: str = Field(..., description="Next billing date")
    on_demand: bool = Field(..., description="On demand subscription")
    payment_frequency_count: int = Field(..., description="Payment frequency count")
    payment_frequency_interval: str = Field(
        ..., description="Payment frequency interval"
    )
    previous_billing_date: str = Field(..., description="Previous billing date")
    product_id: str = Field(..., description="Product ID")
    quantity: int = Field(..., description="Quantity")
    recurring_pre_tax_amount: int = Field(..., description="Recurring pre-tax amount")
    status: str = Field(..., description="Subscription status")
    subscription_id: str = Field(..., description="Subscription ID")
    subscription_period_count: int = Field(..., description="Subscription period count")
    subscription_period_interval: str = Field(
        ..., description="Subscription period interval"
    )
    tax_inclusive: bool = Field(..., description="Tax inclusive")
    trial_period_days: int = Field(..., description="Trial period days")
    cancelled_at: Optional[str] = Field(None, description="Cancelled at")
    discount_id: Optional[str] = Field(None, description="Discount ID")


# Database Models (Internal)
class PlanDB(BaseModel):
    """Database model for subscription plan."""

    id: Optional[str] = Field(None, alias="_id")
    dodo_product_id: str = Field(..., description="Dodo product ID")
    name: str = Field(..., description="Plan name")
    description: Optional[str] = Field(None, description="Plan description")
    amount: int = Field(..., description="Plan amount")
    currency: str = Field(..., description="Currency")
    duration: str = Field(..., description="Billing duration")
    max_users: Optional[int] = Field(None, description="Maximum users")
    features: List[str] = Field(default_factory=list, description="Features")
    is_active: bool = Field(True, description="Active status")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Update timestamp"
    )

    class Config:
        populate_by_name = True
        allow_population_by_field_name = True


class SubscriptionDB(BaseModel):
    """Database model for subscription."""

    id: Optional[str] = Field(None, alias="_id")
    dodo_subscription_id: str = Field(..., description="Dodo subscription ID")
    user_id: str = Field(..., description="User ID")
    product_id: str = Field(..., description="Product ID")
    status: str = Field(..., description="Subscription status")
    quantity: int = Field(1, description="Quantity")
    payment_link: Optional[str] = Field(None, description="Payment link URL")
    webhook_processed_at: Optional[datetime] = Field(
        None, description="Webhook processing timestamp"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Update timestamp"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional data"
    )

    class Config:
        populate_by_name = True
        allow_population_by_field_name = True


class PaymentDB(BaseModel):
    """Database model for payment."""

    id: Optional[str] = Field(None, alias="_id")
    dodo_subscription_id: str = Field(..., description="Dodo subscription ID")
    user_id: str = Field(..., description="User ID")
    subscription_id: Optional[str] = Field(None, description="Internal subscription ID")
    amount: int = Field(..., description="Payment amount")
    currency: str = Field(..., description="Currency")
    status: str = Field(..., description="Payment status")
    description: Optional[str] = Field(None, description="Payment description")
    webhook_processed_at: Optional[datetime] = Field(
        None, description="Webhook processing timestamp"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Creation timestamp"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional data"
    )


class PaymentVerificationResponse(BaseModel):
    payment_completed: bool
    subscription_id: Optional[str] = None
    message: str
