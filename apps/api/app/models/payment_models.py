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


class SubscriptionStatus(str, Enum):
    """Subscription status with clear definitions."""

    PENDING = "pending"  # Payment link created, waiting for payment
    ACTIVE = "active"  # Active with successful payment
    ON_HOLD = "on_hold"  # Temporarily paused
    CANCELLED = "cancelled"  # Cancelled by user or system
    FAILED = "failed"  # Payment failed
    EXPIRED = "expired"  # Expired subscription


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


class PaymentVerificationResponse(BaseModel):
    payment_completed: bool
    subscription_id: Optional[str] = None
    message: str
