"""
Clean payment router for Dodo Payments integration.
Single service approach - simple and maintainable.
"""

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.rate_limiter import limiter
from app.constants.log_tags import LogTag
from app.models.payment_models import (
    CreateSubscriptionRequest,
    PaymentVerificationResponse,
    PlanResponse,
    UserSubscriptionStatus,
)
from app.services.payments.payment_service import payment_service
from app.services.payments.payment_webhook_service import payment_webhook_service
from shared.py.wide_events import log

router = APIRouter()


@router.get("/plans", response_model=list[PlanResponse])
@limiter.limit("30/minute")
# evlog-map-disable-next-line audit -- read-only plan catalog lookup, no state change to audit
async def get_plans_endpoint(request: Request, active_only: bool = True):
    """Get all available subscription plans."""
    log.set(payment={"operation": "get_plans"})
    try:
        return await payment_service.get_plans(active_only=active_only)
    except Exception as e:
        log.error(
            f"{LogTag.PAYMENT} Error getting plans",
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to get plans")


@router.post("/subscriptions")
@limiter.limit("5/minute")
async def create_subscription_endpoint(
    request: Request,
    subscription_data: CreateSubscriptionRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new subscription and return payment link."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    log.set(
        user={"id": user_id},
        payment={
            "operation": "create_checkout",
            "plan_type": str(subscription_data.product_id)
            if subscription_data.product_id
            else None,
        },
    )
    try:
        result = await payment_service.create_subscription(
            user_id, subscription_data.product_id, subscription_data.quantity
        )
        log.audit(
            "subscription checkout created",
            actor=user_id,
            resource=str(subscription_data.product_id) if subscription_data.product_id else None,
            provider="dodo",
        )
        return result
    except Exception as e:
        log.error(
            f"{LogTag.PAYMENT} Error creating subscription",
            user_id=user_id,
            product_id=str(subscription_data.product_id) if subscription_data.product_id else None,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to create subscription")


@router.post("/verify-payment", response_model=PaymentVerificationResponse)
@limiter.limit("20/minute")
async def verify_payment_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Verify if user's payment has been completed."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    log.set(
        user={"id": user_id},
        payment={"operation": "verify_payment"},
    )
    try:
        result = await payment_service.verify_payment_completion(user_id)
        log.audit("payment verification completed", actor=user_id, provider="dodo")
        return PaymentVerificationResponse(**result)
    except Exception as e:
        log.error(
            f"{LogTag.PAYMENT} Error verifying payment",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to verify payment")


@router.get("/subscription-status", response_model=UserSubscriptionStatus)
@limiter.limit("60/minute")
# evlog-map-disable-next-line audit -- read-only subscription status lookup, no state change to audit
async def get_subscription_status_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Get user's current subscription status."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    log.set(
        user={"id": user_id},
        payment={"operation": "get_status"},
    )
    try:
        return await payment_service.get_user_subscription_status(user_id)
    except Exception as e:
        log.error(
            f"{LogTag.PAYMENT} Error getting subscription status",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to get subscription status")


@router.post("/webhooks/dodo")
async def handle_dodo_webhook(
    request: Request,
    webhook_id: str = Header(..., alias="webhook-id"),
    webhook_timestamp: str = Header(..., alias="webhook-timestamp"),
    webhook_signature: str = Header(..., alias="webhook-signature"),
):
    """Handle incoming webhooks from Dodo Payments with signature verification."""
    try:
        # Get raw body for signature verification
        body = await request.body()
        payload = body.decode("utf-8")

        # Prepare headers for verification
        headers = {
            "webhook-id": webhook_id,
            "webhook-timestamp": webhook_timestamp,
            "webhook-signature": webhook_signature,
        }

        # Verify webhook signature using Standard Webhooks library
        if not payment_webhook_service.verify_webhook_signature(payload, headers):
            log.warning(f"{LogTag.PAYMENT} Invalid webhook signature", webhook_id=webhook_id)
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        # Parse webhook data
        webhook_data = json.loads(payload)

        event_type = webhook_data.get("type", "unknown")
        log.set(
            payment={
                "operation": "webhook",
                "event_type": event_type,
            }
        )

        # Process the webhook with idempotency check using webhook_id
        result = await payment_webhook_service.process_webhook(webhook_data, webhook_id)

        log.audit(
            "payment webhook processed",
            actor="dodo-webhook",
            event_type=result.event_type,
            processing_status=result.status,
        )
        log.info(
            f"{LogTag.PAYMENT} Webhook processed",
            event_type=result.event_type,
            processing_status=result.status,
        )
        return {
            "status": "success",
            "event_type": result.event_type,
            "processing_status": result.status,
            "message": result.message,
        }

    except HTTPException:
        raise
    except json.JSONDecodeError as exc:
        log.error(
            f"{LogTag.PAYMENT} Invalid JSON in webhook payload", error_type=type(exc).__name__
        )
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        log.error(
            f"{LogTag.PAYMENT} Error processing webhook",
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Webhook processing failed")
