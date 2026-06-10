"""
Payment and subscription related models for Dodo Payments integration.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PlanType(str, Enum):
    """Subscription plan types."""

    FREE = "free"
    PRO = "pro"


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


# Response Models
class PlanResponse(BaseModel):
    """Response model for subscription plan."""

    id: str = Field(..., description="Plan ID")
    dodo_product_id: str = Field(..., description="Dodo product ID")
    name: str = Field(..., description="Plan name")
    description: str | None = Field(None, description="Plan description")
    amount: int = Field(..., description="Plan amount")
    currency: str = Field(..., description="Currency")
    duration: str = Field(..., description="Billing duration")
    max_users: int | None = Field(None, description="Maximum users")
    features: list[str] = Field(default_factory=list, description="Features")
    is_active: bool = Field(..., description="Active status")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")


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
class PlanDB(BaseModel):
    """Database model for subscription plan."""

    id: str | None = Field(None, alias="_id")
    dodo_product_id: str = Field(..., description="Dodo product ID")
    name: str = Field(..., description="Plan name")
    description: str | None = Field(None, description="Plan description")
    amount: int = Field(..., description="Plan amount")
    currency: str = Field(..., description="Currency")
    duration: str = Field(..., description="Billing duration")
    max_users: int | None = Field(None, description="Maximum users")
    features: list[str] = Field(default_factory=list, description="Features")
    is_active: bool = Field(True, description="Active status")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Update timestamp",
    )

    class Config:
        populate_by_name = True
        allow_population_by_field_name = True


class PaymentVerificationResponse(BaseModel):
    payment_completed: bool
    subscription_id: str | None = None
    message: str
