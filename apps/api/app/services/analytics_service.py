"""
Analytics service for server-side PostHog event tracking.
Provides type-safe event tracking with consistent naming conventions.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from app.config.loggers import app_logger as logger
from app.core.lazy_loader import providers


# Event name constants for consistent tracking
class AnalyticsEvents:
    """Analytics event names matching frontend conventions."""

    # Keep only backend-relevant events (auth signup, payments, subscriptions)
    USER_SIGNED_UP = "user:signed_up"

    # Payment events (used by payment webhook processing)
    PAYMENT_SUCCEEDED = "payment:succeeded"
    PAYMENT_FAILED = "payment:failed"
    PAYMENT_REFUNDED = "payment:refunded"

    # Subscription events (used by payment webhook processing)
    SUBSCRIPTION_ACTIVATED = "subscription:activated"
    SUBSCRIPTION_RENEWED = "subscription:renewed"
    SUBSCRIPTION_CANCELLED = "subscription:cancelled"
    SUBSCRIPTION_EXPIRED = "subscription:expired"
    SUBSCRIPTION_FAILED = "subscription:failed"


def _get_posthog_client():
    """Get the PostHog client from providers."""
    return providers.get("posthog")


def identify_user(
    user_id: str,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """
    Identify a user in PostHog with their properties.

    Args:
        user_id: PostHog distinct_id - use EMAIL for consistency with frontend.
                 Frontend identifies users by email, so backend must match.
        properties: User properties to set
    """
    client = _get_posthog_client()
    if client is None:
        logger.debug("PostHog client not available, skipping identify")
        return

    try:
        user_properties = {
            **(properties or {}),
            "$set_once": {
                "first_seen": datetime.now(timezone.utc).isoformat(),
            },
        }
        client.identify(user_id, user_properties)
    except Exception as e:
        logger.error(f"Failed to identify user in PostHog: {e}")


def capture_event(
    user_id: str,
    event: str,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """
    Capture an analytics event in PostHog.

    Args:
        user_id: Unique identifier for the user
        event: Event name
        properties: Event properties
    """
    client = _get_posthog_client()
    if client is None:
        logger.debug(f"PostHog client not available, skipping event: {event}")
        return

    try:
        event_properties = {
            **(properties or {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        client.capture(user_id, event, event_properties)
    except Exception as e:
        logger.error(f"Failed to capture event {event} in PostHog: {e}")


def track_signup(
    user_id: str,
    email: str,
    name: Optional[str] = None,
    signup_method: str = "workos",
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """
    Track a user signup event.

    Args:
        user_id: User's unique identifier
        email: User's email address
        name: User's display name
        signup_method: How the user signed up (workos, google, email)
        properties: Additional properties
    """
    # First identify the user
    identify_user(
        user_id,
        {
            "email": email,
            "name": name,
            "signup_method": signup_method,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Then capture the signup event
    capture_event(
        user_id,
        AnalyticsEvents.USER_SIGNED_UP,
        {
            "email": email,
            "name": name,
            "signup_method": signup_method,
            **(properties or {}),
        },
    )


def track_subscription_event(
    user_id: str,
    event_type: str,
    subscription_id: Optional[str] = None,
    plan_name: Optional[str] = None,
    amount: Optional[float] = None,
    currency: Optional[str] = None,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """
    Track subscription-related events.

    Args:
        user_id: User's unique identifier
        event_type: Type of subscription event
        subscription_id: Subscription identifier
        plan_name: Name of the plan
        amount: Subscription amount
        currency: Currency code
        properties: Additional properties
    """
    event_properties = {
        "subscription_id": subscription_id,
        "plan_name": plan_name,
        "amount": amount,
        "currency": currency,
        **(properties or {}),
    }
    # Remove None values
    event_properties = {k: v for k, v in event_properties.items() if v is not None}

    capture_event(user_id, event_type, event_properties)

    # Update user properties for subscription status
    if event_type == AnalyticsEvents.SUBSCRIPTION_ACTIVATED:
        client = _get_posthog_client()
        if client:
            try:
                client.identify(
                    user_id,
                    {
                        "plan": plan_name,
                        "subscription_status": "active",
                        "subscription_activated_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"Failed to update user subscription properties: {e}")


def track_payment_event(
    user_id: str,
    event_type: str,
    payment_id: Optional[str] = None,
    amount: Optional[float] = None,
    currency: Optional[str] = None,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """
    Track payment-related events.

    Args:
        user_id: User's unique identifier
        event_type: Type of payment event
        payment_id: Payment identifier
        amount: Payment amount
        currency: Currency code
        properties: Additional properties
    """
    event_properties = {
        "payment_id": payment_id,
        "amount": amount,
        "currency": currency,
        **(properties or {}),
    }
    # Remove None values
    event_properties = {k: v for k, v in event_properties.items() if v is not None}

    capture_event(user_id, event_type, event_properties)


def flush_events() -> None:
    """Flush any pending events to PostHog."""
    client = _get_posthog_client()
    if client:
        try:
            client.flush()
        except Exception as e:
            logger.error(f"Failed to flush PostHog events: {e}")
