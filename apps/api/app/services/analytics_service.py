"""
Analytics service for server-side PostHog event tracking.
Provides type-safe event tracking with consistent naming conventions.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from posthog import Posthog

from app.constants.auth import LOGIN_METHOD_WORKOS
from app.core.lazy_loader import providers
from app.models.payment_models import PlanType, SubscriptionStatus
from shared.py.wide_events import log


# Event name constants for consistent tracking
class AnalyticsEvents(StrEnum):
    """Backend-relevant analytics event names (matching frontend conventions)."""

    # Auth
    USER_SIGNED_UP = "user:signed_up"
    USER_LOGGED_IN = "user:logged_in"
    USER_LOGGED_OUT = "user:logged_out"

    # Core product actions
    CHAT_MESSAGE_SUBMITTED = "chat:message_submitted"
    WORKFLOW_CREATED = "workflow:created"
    WORKFLOW_EXECUTED = "workflow:executed"
    WORKFLOW_ACTIVATED = "workflow:activated"
    WORKFLOW_PUBLISHED = "workflow:published"
    PAYMENT_CHECKOUT_STARTED = "payment:checkout_started"
    SUBSCRIPTION_CANCELLATION_REQUESTED = "subscription:cancellation_requested"
    FEEDBACK_MESSAGE_SUBMITTED = "feedback:message_submitted"
    SESSION_ARTIFACT_PINNED = "session:artifact_pinned"
    PROFILE_UPDATED = "profile:updated"

    # Lifecycle email
    NURTURE_EMAIL_SENT = "nurture:email_sent"

    # Payments (used by payment webhook processing)
    PAYMENT_SUCCEEDED = "payment:succeeded"
    PAYMENT_FAILED = "payment:failed"
    PAYMENT_REFUNDED = "payment:refunded"

    # Subscription lifecycle (used by payment webhook processing)
    SUBSCRIPTION_ACTIVATED = "subscription:activated"
    SUBSCRIPTION_RENEWED = "subscription:renewed"
    SUBSCRIPTION_CANCELLED = "subscription:cancelled"
    SUBSCRIPTION_EXPIRED = "subscription:expired"
    SUBSCRIPTION_FAILED = "subscription:failed"
    RATE_LIMIT_HIT = "rate_limit_hit"


def _get_posthog_client() -> Posthog | None:
    """Get the PostHog client from providers."""
    client: Posthog | None = providers.get("posthog")
    return client


def identify_user(
    user_id: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """
    Identify a user in PostHog with their properties.

    Args:
        user_id: Stable PostHog distinct_id from the application's user record.
        properties: Person properties to set
    """
    client = _get_posthog_client()
    if client is None:
        log.debug("PostHog client not available, skipping identify")
        return

    try:
        user_properties = {**(properties or {})}
        client.set(distinct_id=user_id, properties=user_properties)
        client.set_once(
            distinct_id=user_id,
            properties={"first_seen": datetime.now(UTC).isoformat()},
        )
    except Exception as e:
        log.error(
            "Failed to identify user in PostHog",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


def capture_context_event(
    event: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Capture an event attributed by the active PostHog request context."""
    client = _get_posthog_client()
    if client is None:
        log.debug("PostHog client not available, skipping event", event=event)
        return

    try:
        client.capture(
            event=event,
            properties={
                **(properties or {}),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as e:
        log.error(
            "Failed to capture event in PostHog",
            event=event,
            error=str(e),
            error_type=type(e).__name__,
        )


def capture_event(
    user_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
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
        log.debug("PostHog client not available, skipping event", event=event)
        return

    log.set(analytics={"user_id": user_id, "event": event})
    try:
        event_properties = {
            **(properties or {}),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        client.capture(
            event=event,
            distinct_id=user_id,
            properties=event_properties,
        )
    except Exception as e:
        log.error(
            "Failed to capture event in PostHog",
            event=event,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


def track_signup(
    user_id: str,
    email: str,
    name: str | None = None,
    signup_method: str = LOGIN_METHOD_WORKOS,
    properties: dict[str, Any] | None = None,
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
    identify_user(
        user_id,
        {
            "email": email,
            "name": name,
            "signup_method": signup_method,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )

    capture_event(
        user_id,
        AnalyticsEvents.USER_SIGNED_UP,
        {
            "signup_method": signup_method,
            **(properties or {}),
        },
    )


def track_login(
    user_id: str,
    email: str,
    name: str | None = None,
    login_method: str = LOGIN_METHOD_WORKOS,
    properties: dict[str, Any] | None = None,
) -> None:
    """
    Track a user login event.

    Args:
        user_id: User's unique identifier
        email: User's email address
        name: User's display name
        login_method: How the user logged in (workos, google, email)
        properties: Additional properties
    """
    identify_user(
        user_id,
        {
            "email": email,
            "name": name,
            "last_login_method": login_method,
            "last_login_at": datetime.now(UTC).isoformat(),
        },
    )

    capture_event(
        user_id,
        AnalyticsEvents.USER_LOGGED_IN,
        {
            "login_method": login_method,
            **(properties or {}),
        },
    )


def track_logout(
    user_id: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """
    Track a user logout event.

    Args:
        user_id: User's unique identifier
        properties: Additional properties
    """
    capture_event(
        user_id,
        AnalyticsEvents.USER_LOGGED_OUT,
        properties,
    )


def track_subscription_event(
    user_id: str,
    event_type: AnalyticsEvents,
    subscription_id: str | None = None,
    plan_name: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
    properties: dict[str, Any] | None = None,
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
    log.set(
        subscription={
            "user_id": user_id,
            "event_type": event_type,
            "plan_name": plan_name,
            "subscription_id": subscription_id,
        }
    )
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

    # Update the user's subscription metadata (person properties, not an emitted
    # event) so any chart can segment pro vs free. `is_subscribed` is the
    # canonical flag; a cancellation keeps access until the plan actually expires.
    match event_type:
        case AnalyticsEvents.SUBSCRIPTION_ACTIVATED:
            metadata = {
                "plan": PlanType.PRO,
                "is_subscribed": True,
                "subscription_status": SubscriptionStatus.ACTIVE,
                "subscription_activated_at": datetime.now(UTC).isoformat(),
            }
        case AnalyticsEvents.SUBSCRIPTION_RENEWED:
            metadata = {
                "plan": PlanType.PRO,
                "is_subscribed": True,
                "subscription_status": SubscriptionStatus.ACTIVE,
            }
        case AnalyticsEvents.SUBSCRIPTION_CANCELLED:
            metadata = {"subscription_status": SubscriptionStatus.CANCELLED}
        case AnalyticsEvents.SUBSCRIPTION_EXPIRED:
            metadata = {
                "plan": PlanType.FREE,
                "is_subscribed": False,
                "subscription_status": SubscriptionStatus.EXPIRED,
            }
        case _:
            # Non-subscription or no-metadata events (e.g. FAILED) are ignored.
            return

    client = _get_posthog_client()
    if client is None:
        return
    try:
        client.set(distinct_id=user_id, properties=metadata)
    except Exception as e:
        log.error(
            "Failed to update user subscription properties",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


def track_payment_event(
    user_id: str,
    event_type: str,
    payment_id: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
    properties: dict[str, Any] | None = None,
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
