"""
Clean payment router for Dodo Payments integration.
Single service approach - simple and maintainable.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.api.v1.middleware.rate_limiter import limiter
from app.constants.log_tags import LogTag
from app.models.payment_models import (
    CreateSubscriptionRequest,
    CreateSubscriptionResponse,
    PaymentVerificationResponse,
    PlanResponse,
    UserSubscriptionStatus,
)
from app.models.webhook_models import DodoWebhookAckResponse
from app.services.payments.payment_service import payment_service
from app.services.payments.payment_webhook_service import payment_webhook_service
from shared.py.wide_events import log

router = APIRouter()


@router.get("/plans", response_model=list[PlanResponse])
@limiter.limit("30/minute")
async def get_plans_endpoint(request: Request, active_only: bool = True) -> list[PlanResponse]:
    """Get all available subscription plans."""
    log.set(payment={"operation": "get_plans"})
    try:
        return await payment_service.get_plans(active_only=active_only)
    except Exception as e:
        log.error(f"{LogTag.PAYMENT} Error getting plans: {e!s}")
        raise HTTPException(status_code=500, detail="Failed to get plans")


@router.post("/subscriptions")
@limiter.limit("5/minute")
async def create_subscription_endpoint(
    request: Request,
    subscription_data: CreateSubscriptionRequest,
    user_id: str = Depends(get_user_id),
) -> CreateSubscriptionResponse:
    """Create a new subscription and return payment link."""
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
        return await payment_service.create_subscription(
            user_id, subscription_data.product_id, subscription_data.quantity
        )
    except Exception as e:
        log.error(f"{LogTag.PAYMENT} Error creating subscription: {e!s}")
        raise HTTPException(status_code=500, detail="Failed to create subscription")


@router.post("/verify-payment", response_model=PaymentVerificationResponse)
@limiter.limit("20/minute")
async def verify_payment_endpoint(
    request: Request,
    user_id: str = Depends(get_user_id),
) -> PaymentVerificationResponse:
    """Verify if user's payment has been completed."""
    log.set(
        user={"id": user_id},
        payment={"operation": "verify_payment"},
    )
    try:
        return await payment_service.verify_payment_completion(user_id)
    except Exception as e:
        log.error(f"{LogTag.PAYMENT} Error verifying payment: {e!s}")
        raise HTTPException(status_code=500, detail="Failed to verify payment")


@router.get("/subscription-status", response_model=UserSubscriptionStatus)
@limiter.limit("60/minute")
async def get_subscription_status_endpoint(
    request: Request,
    user_id: str = Depends(get_user_id),
) -> UserSubscriptionStatus:
    """Get user's current subscription status."""
    log.set(
        user={"id": user_id},
        payment={"operation": "get_status"},
    )
    try:
        return await payment_service.get_user_subscription_status(user_id)
    except Exception as e:
        log.error(f"{LogTag.PAYMENT} Error getting subscription status: {e!s}")
        raise HTTPException(status_code=500, detail="Failed to get subscription status")


@router.post("/webhooks/dodo")
async def handle_dodo_webhook(
    request: Request,
    webhook_id: str = Header(..., alias="webhook-id"),
    webhook_timestamp: str = Header(..., alias="webhook-timestamp"),
    webhook_signature: str = Header(..., alias="webhook-signature"),
) -> DodoWebhookAckResponse:
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
            log.warning(f"{LogTag.PAYMENT} Invalid webhook signature")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        # Raw provider payload: process_webhook validates it into DodoWebhookEvent and
        # deliberately answers 200/"failed" for shapes it can't parse, so Dodo's retry
        # policy stays driven by the processing result rather than a request rejection.
        webhook_data: dict[str, Any] = json.loads(payload)

        event_type = webhook_data.get("type", "unknown")
        log.set(
            payment={
                "operation": "webhook",
                "event_type": event_type,
            }
        )

        # Process the webhook with idempotency check using webhook_id
        result = await payment_webhook_service.process_webhook(webhook_data, webhook_id)

        log.info(f"{LogTag.PAYMENT} Webhook processed: {result.event_type} - {result.status}")
        return DodoWebhookAckResponse(
            event_type=result.event_type,
            processing_status=result.status,
            message=result.message,
        )

    except HTTPException:
        raise
    except json.JSONDecodeError:
        log.error(f"{LogTag.PAYMENT} Invalid JSON in webhook payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        log.error(f"{LogTag.PAYMENT} Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")
