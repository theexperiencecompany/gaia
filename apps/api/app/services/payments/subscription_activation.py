"""The single write path that turns an active Dodo subscription into a local row.

Two callers reach it: the ``subscription.active`` webhook, and the payment
verification that reconciles directly against Dodo when that webhook never
arrived. They share this implementation deliberately — a recovered payment and
a delivered one must leave identical state, and a second activation written
next to the verification is exactly how the two would drift.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.log_tags import LogTag
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.models.payment_models import SubscriptionDocument
from app.models.webhook_models import DodoSubscriptionData
from app.services.analytics_service import AnalyticsEvents, track_subscription_event
from app.services.email import send_pro_subscription_email
from shared.py.wide_events import log

CENTS_PER_UNIT = 100


@dataclass(frozen=True)
class SubscriptionActivation:
    """``user_id`` is None when the subscription belongs to nobody we know."""

    user_id: str | None
    created: bool


async def reactivate_workflows_safely(user_id: str) -> None:
    """Turn a user's paused automation back on once they're paid again. Never
    raises — a workflow-reactivation failure must not turn an otherwise-successful
    billing webhook into a "failed" result that Dodo would retry."""
    # Deferred import: breaks a circular dependency. `app.decorators.entitlements`
    # imports `payment_service`, which imports this module; a top-level import of
    # `subscription_pause` would drag the whole workflow/triggers/composio stack
    # into that chain, and it reaches back into `app.decorators`.
    from app.services.workflow.subscription_pause import (  # noqa: PLC0415
        reactivate_workflows_for_restored_subscription,
    )

    try:
        await reactivate_workflows_for_restored_subscription(user_id)
    except Exception as e:
        log.error(
            f"{LogTag.PAYMENT} Failed to reactivate workflows for restored subscription",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


async def send_welcome_email_safely(user_id: str) -> None:
    """Welcome the new subscriber. Never raises — see ``reactivate_workflows_safely``."""
    try:
        user = await user_repository.get(user_id)
        if user and user.email:
            await send_pro_subscription_email(
                user_name=user.first_name or "User",
                user_email=user.email,
            )
            log.info(f"{LogTag.PAYMENT} Welcome email sent to", email=user.email)
    except Exception as e:
        log.error(
            f"{LogTag.PAYMENT} Failed to send welcome email",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


async def resolve_subscription_owner(sub_data: DodoSubscriptionData) -> str | None:
    """The GAIA user this subscription belongs to.

    Checkout stamps the user id into metadata; the customer email is the
    fallback for sessions minted before that (or created in Dodo's dashboard).
    Callers acting on a client-supplied subscription id must compare this
    against the authenticated user before activating anything.
    """
    metadata_user_id = sub_data.metadata.get("user_id")
    if metadata_user_id:
        return str(metadata_user_id)

    user = await user_repository.get_by_email(sub_data.customer.email)
    return str(user.id) if user else None


async def activate_subscription(sub_data: DodoSubscriptionData) -> SubscriptionActivation:
    """Create the local subscription row for an active Dodo subscription.

    Idempotent: an already-recorded subscription only re-enables the workflows
    that lapsed, so a replayed webhook and a verification racing it converge.
    """
    existing = await subscription_repository.get_by_dodo_id(sub_data.subscription_id)
    if existing:
        log.info(
            f"{LogTag.PAYMENT} Subscription already exists",
            subscription_id=sub_data.subscription_id,
        )
        await reactivate_workflows_safely(existing.user_id)
        return SubscriptionActivation(user_id=existing.user_id, created=False)

    user_id = await resolve_subscription_owner(sub_data)
    if not user_id:
        log.error(
            f"{LogTag.PAYMENT} User not found for subscription",
            subscription_id=sub_data.subscription_id,
        )
        return SubscriptionActivation(user_id=None, created=False)

    now = datetime.now(UTC)
    # Built as a dict, not keyword construction: SubscriptionDocument declares
    # only the fields GAIA reads and keeps Dodo's remaining billing fields via
    # ``extra="allow"``, which model_validate preserves and kwargs would reject.
    await subscription_repository.create(
        SubscriptionDocument.model_validate(
            {
                "dodo_subscription_id": sub_data.subscription_id,
                "user_id": user_id,
                "product_id": sub_data.product_id,
                "status": "active",
                "quantity": sub_data.quantity,
                "currency": sub_data.currency,
                "recurring_pre_tax_amount": sub_data.recurring_pre_tax_amount,
                "payment_frequency_count": sub_data.payment_frequency_count,
                "payment_frequency_interval": sub_data.payment_frequency_interval,
                "subscription_period_count": sub_data.subscription_period_count,
                "subscription_period_interval": sub_data.subscription_period_interval,
                "next_billing_date": sub_data.next_billing_date,
                "previous_billing_date": sub_data.previous_billing_date,
                "created_at": now,
                "updated_at": now,
                "metadata": sub_data.metadata,
            }
        )
    )

    track_subscription_event(
        user_id=user_id,
        event_type=AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
        subscription_id=sub_data.subscription_id,
        plan_name="Pro",
        amount=sub_data.recurring_pre_tax_amount / CENTS_PER_UNIT
        if sub_data.recurring_pre_tax_amount
        else None,
        currency=sub_data.currency,
    )

    await send_welcome_email_safely(user_id)
    await reactivate_workflows_safely(user_id)

    log.info(f"{LogTag.PAYMENT} Subscription activated", subscription_id=sub_data.subscription_id)
    return SubscriptionActivation(user_id=user_id, created=True)
