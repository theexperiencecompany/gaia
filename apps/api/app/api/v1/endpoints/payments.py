"""
Clean payment router for Dodo Payments integration.
Single service approach - simple and maintainable.
"""

import json
from typing import List

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.rate_limiter import limiter
from app.config.loggers import general_logger as logger
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

    return await payment_service.get_user_subscription_status(user_id)


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
            logger.warning("Invalid webhook signature")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        # Parse webhook data
        webhook_data = json.loads(payload)

        # Process the webhook with idempotency check using webhook_id
        result = await payment_webhook_service.process_webhook(webhook_data, webhook_id)

        logger.info(f"Webhook processed: {result.event_type} - {result.status}")
        return {
            "status": "success",
            "event_type": result.event_type,
            "processing_status": result.status,
            "message": result.message,
        }

    except HTTPException:
        raise
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")
