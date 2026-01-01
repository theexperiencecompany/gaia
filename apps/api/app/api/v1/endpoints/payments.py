"""
Clean payment router for Dodo Payments integration.
Single service approach - simple and maintainable.
"""

import json
from typing import List

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.rate_limiter import limiter
from app.config.loggers import general_logger as logger, get_current_event
from app.models.payment_models import (
    CreateSubscriptionRequest,
    PaymentVerificationResponse,
    PlanResponse,
    UserSubscriptionStatus,
)
from app.services.payments.payment_service import payment_service
from app.services.payments.payment_webhook_service import payment_webhook_service
from fastapi import APIRouter, Depends, Header, HTTPException, Request

router = APIRouter()


@router.get("/plans", response_model=List[PlanResponse])
@limiter.limit("30/minute")
async def get_plans_endpoint(request: Request, active_only: bool = True):
    """Get all available subscription plans."""
    wide_event = get_current_event()
    if wide_event:
        wide_event.set_operation(operation="get_plans", resource_type="plan")
        wide_event.set_business_context(active_only=active_only)

    return await payment_service.get_plans(active_only=active_only)


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

    wide_event = get_current_event()
    if wide_event:
        wide_event.set_operation(
            operation="create_subscription",
            resource_type="subscription",
        )
        wide_event.set_business_context(
            product_id=subscription_data.product_id,
            quantity=subscription_data.quantity,
        )

    return await payment_service.create_subscription(
        user_id, subscription_data.product_id, subscription_data.quantity
    )


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

    wide_event = get_current_event()
    if wide_event:
        wide_event.set_operation(
            operation="verify_payment",
            resource_type="payment",
        )

    result = await payment_service.verify_payment_completion(user_id)
    return PaymentVerificationResponse(**result)


@router.get("/subscription-status", response_model=UserSubscriptionStatus)
@limiter.limit("60/minute")
async def get_subscription_status_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Get user's current subscription status."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    wide_event = get_current_event()
    if wide_event:
        wide_event.set_operation(
            operation="get_subscription_status",
            resource_type="subscription",
        )

    return await payment_service.get_user_subscription_status(user_id)


@router.post("/webhooks/dodo")
async def handle_dodo_webhook(
    request: Request,
    webhook_id: str = Header(..., alias="webhook-id"),
    webhook_timestamp: str = Header(..., alias="webhook-timestamp"),
    webhook_signature: str = Header(..., alias="webhook-signature"),
):
    """Handle incoming webhooks from Dodo Payments with signature verification."""
    wide_event = get_current_event()
    if wide_event:
        wide_event.set_operation(
            operation="handle_webhook",
            resource_type="webhook",
        )
        wide_event.set_business_context(
            webhook_id=webhook_id,
            webhook_source="dodo_payments",
        )

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
            logger.warning(
                "webhook_signature_invalid",
                webhook_id=webhook_id,
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        # Parse webhook data
        webhook_data = json.loads(payload)
        event_type = webhook_data.get("type", "unknown")

        if wide_event:
            wide_event.set_business_context(
                webhook_event_type=event_type,
            )

        # Process the webhook
        result = await payment_webhook_service.process_webhook(webhook_data)

        logger.info(
            "webhook_processed",
            webhook_id=webhook_id,
            event_type=result.event_type,
            status=result.status,
        )
        return {
            "status": "success",
            "event_type": result.event_type,
            "processing_status": result.status,
            "message": result.message,
        }

    except HTTPException:
        raise
    except json.JSONDecodeError:
        logger.error(
            "webhook_invalid_json",
            webhook_id=webhook_id,
        )
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(
            "webhook_processing_failed",
            webhook_id=webhook_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(status_code=500, detail="Webhook processing failed")
