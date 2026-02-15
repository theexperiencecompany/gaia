"""
Clean payment webhook service for Dodo Payments integration.
Handles webhook events and updates database state accordingly.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from app.config.loggers import general_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import (
    processed_webhooks_collection,
    subscriptions_collection,
    users_collection,
)
from app.models.webhook_models import (
    DodoWebhookEvent,
    DodoWebhookEventType,
    DodoWebhookProcessingResult,
)
from app.services.analytics_service import (
    AnalyticsEvents,
    track_payment_event,
    track_subscription_event,
)
from app.utils.email_utils import send_pro_subscription_email
from bson import ObjectId
from standardwebhooks.webhooks import Webhook


class PaymentWebhookService:
    """Clean service for handling Dodo payment webhooks."""

    def __init__(self):
        self.webhook_secret = settings.DODO_WEBHOOK_PAYMENTS_SECRET
        # Initialize Standard Webhooks verifier
        if self.webhook_secret:
            try:
                # The secret should be base64 encoded for Standard Webhooks
                self.webhook_verifier = Webhook(self.webhook_secret)
            except Exception as e:
                logger.error(f"Failed to initialize webhook verifier: {e}")
                self.webhook_verifier = None
        else:
            self.webhook_verifier = None

        self.handlers = {
            DodoWebhookEventType.PAYMENT_SUCCEEDED: self._handle_payment_succeeded,
            DodoWebhookEventType.PAYMENT_FAILED: self._handle_payment_failed,
            DodoWebhookEventType.PAYMENT_PROCESSING: self._handle_payment_processing,
            DodoWebhookEventType.PAYMENT_CANCELLED: self._handle_payment_cancelled,
            DodoWebhookEventType.SUBSCRIPTION_ACTIVE: self._handle_subscription_active,
            DodoWebhookEventType.SUBSCRIPTION_RENEWED: self._handle_subscription_renewed,
            DodoWebhookEventType.SUBSCRIPTION_CANCELLED: self._handle_subscription_cancelled,
            DodoWebhookEventType.SUBSCRIPTION_EXPIRED: self._handle_subscription_expired,
            DodoWebhookEventType.SUBSCRIPTION_FAILED: self._handle_subscription_failed,
            DodoWebhookEventType.SUBSCRIPTION_ON_HOLD: self._handle_subscription_on_hold,
            DodoWebhookEventType.SUBSCRIPTION_PLAN_CHANGED: self._handle_subscription_plan_changed,
        }

    def verify_webhook_signature(self, payload: str, headers: Dict[str, str]) -> bool:
        """
        Verify webhook signature using Standard Webhooks library.

        Args:
            payload: The raw JSON payload as string
            headers: Dictionary of headers from the webhook request
        """
        if not self.webhook_verifier:
            logger.warning(
                "No webhook verifier configured - skipping signature verification"
            )
            return True

        # Skip verification in development
        if settings.ENV != "production":
            logger.info("Development mode - skipping webhook signature verification")
            return True

        try:
            logger.info("Verifying webhook signature using Standard Webhooks library")

            # The Standard Webhooks library expects headers in the correct format
            # Convert headers to the expected format (lowercase with dashes)
            webhook_headers = {}
            for key, value in headers.items():
                # Convert header names to the expected format
                if key.lower() == "webhook-id":
                    webhook_headers["webhook-id"] = value
                elif key.lower() == "webhook-timestamp":
                    webhook_headers["webhook-timestamp"] = value
                elif key.lower() == "webhook-signature":
                    webhook_headers["webhook-signature"] = value

            # Verify using Standard Webhooks library
            self.webhook_verifier.verify(payload.encode("utf-8"), webhook_headers)

            logger.info("Webhook signature verification successful!")
            return True

        except Exception as e:
            logger.warning(f"Webhook signature verification failed: {e}")
            return False

    async def _is_webhook_processed(self, webhook_id: str) -> bool:
        """Check if webhook has already been processed."""
        processed = await processed_webhooks_collection.find_one(
            {"webhook_id": webhook_id}
        )
        return processed is not None

    async def _mark_webhook_as_processed(
        self, webhook_id: str, event_type: str, result: DodoWebhookProcessingResult
    ) -> None:
        """Store webhook ID as processed in database."""
        try:
            await processed_webhooks_collection.insert_one(
                {
                    "webhook_id": webhook_id,
                    "event_type": event_type,
                    "status": result.status,
                    "message": result.message,
                    "payment_id": result.payment_id,
                    "subscription_id": result.subscription_id,
                    "processed_at": datetime.now(timezone.utc),
                }
            )
        except Exception as e:
            logger.error(f"Failed to store processed webhook ID: {e}")

    async def process_webhook(
        self, webhook_data: Dict[str, Any], webhook_id: str
    ) -> DodoWebhookProcessingResult:
        """
        Process Dodo payment webhook with idempotency check.

        Args:
            webhook_data: The webhook payload
            webhook_id: Unique webhook ID from webhook-id header for idempotency

        Returns:
            Processing result
        """
        try:
            # Check if webhook has already been processed
            if await self._is_webhook_processed(webhook_id):
                logger.info(f"Webhook {webhook_id} already processed, skipping")
                return DodoWebhookProcessingResult(
                    event_type=webhook_data.get("type", "unknown"),
                    status="ignored",
                    message="Webhook already processed",
                )

            event = DodoWebhookEvent(**webhook_data)

            handler = self.handlers.get(event.type)
            if not handler:
                result = DodoWebhookProcessingResult(
                    event_type=event.type.value,
                    status="ignored",
                    message=f"No handler for {event.type}",
                )
                # Store even ignored webhooks to prevent reprocessing
                await self._mark_webhook_as_processed(webhook_id, event.type.value, result)
                return result

            result = await handler(event)
            logger.info(f"Webhook processed: {event.type} - {result.status}")

            # Store webhook as processed after successful handler execution
            await self._mark_webhook_as_processed(webhook_id, event.type.value, result)
            return result

        except Exception as e:
            logger.error(f"Webhook processing failed: {e}")
            return DodoWebhookProcessingResult(
                event_type=webhook_data.get("type", "unknown"),
                status="failed",
                message=f"Processing error: {str(e)}",
            )

    async def _get_user_email_from_metadata(
        self, metadata: Dict[str, Any]
    ) -> str | None:
        """Get user email from metadata or database lookup."""
        user_id = metadata.get("user_id")
        if user_id:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user:
                return user.get("email")
        return None

    # Payment event handlers
    async def _handle_payment_succeeded(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle successful payment - just log, subscription activation handles the rest."""
        payment_data = event.get_payment_data()
        if not payment_data:
            raise ValueError("Invalid payment data")

        logger.info(f"Payment succeeded: {payment_data.payment_id}")

        # Track payment success in PostHog
        user_email = await self._get_user_email_from_metadata(payment_data.metadata)
        if user_email:
            track_payment_event(
                user_id=user_email,
                event_type=AnalyticsEvents.PAYMENT_SUCCEEDED,
                payment_id=payment_data.payment_id,
                amount=payment_data.total_amount / 100
                if payment_data.total_amount
                else None,
                currency=payment_data.currency,
            )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Payment success logged",
            payment_id=payment_data.payment_id,
            subscription_id=payment_data.subscription_id,
        )

    async def _handle_payment_failed(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle failed payment."""
        payment_data = event.get_payment_data()
        if not payment_data:
            raise ValueError("Invalid payment data")

        logger.warning(f"Payment failed: {payment_data.payment_id}")

        # Track payment failure in PostHog
        user_email = await self._get_user_email_from_metadata(payment_data.metadata)
        if user_email:
            track_payment_event(
                user_id=user_email,
                event_type=AnalyticsEvents.PAYMENT_FAILED,
                payment_id=payment_data.payment_id,
                amount=payment_data.total_amount / 100
                if payment_data.total_amount
                else None,
                currency=payment_data.currency,
            )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Payment failure logged",
            payment_id=payment_data.payment_id,
            subscription_id=payment_data.subscription_id,
        )

    async def _handle_payment_processing(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle payment processing status."""
        payment_data = event.get_payment_data()
        if not payment_data:
            raise ValueError("Invalid payment data")

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Payment processing noted",
            payment_id=payment_data.payment_id,
            subscription_id=payment_data.subscription_id,
        )

    async def _handle_payment_cancelled(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle cancelled payment."""
        payment_data = event.get_payment_data()
        if not payment_data:
            raise ValueError("Invalid payment data")

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Payment cancellation noted",
            payment_id=payment_data.payment_id,
            subscription_id=payment_data.subscription_id,
        )

    # Subscription event handlers
    async def _handle_subscription_active(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle subscription activation - CREATE subscription record here."""
        sub_data = event.get_subscription_data()
        if not sub_data:
            raise ValueError("Invalid subscription data")

        # Check if subscription already exists
        existing = await subscriptions_collection.find_one(
            {"dodo_subscription_id": sub_data.subscription_id}
        )

        if existing:
            logger.info(f"Subscription already exists: {sub_data.subscription_id}")
            return DodoWebhookProcessingResult(
                event_type=event.type.value,
                status="processed",
                message="Subscription already active",
                subscription_id=sub_data.subscription_id,
            )

        # Find user by email or metadata
        user_id = sub_data.metadata.get("user_id")
        user_email = sub_data.customer.email
        if not user_id:
            user = await users_collection.find_one({"email": user_email})
            if not user:
                logger.error(
                    f"User not found for subscription: {sub_data.subscription_id}"
                )
                return DodoWebhookProcessingResult(
                    event_type=event.type.value,
                    status="failed",
                    message="User not found",
                    subscription_id=sub_data.subscription_id,
                )
            user_id = str(user["_id"])

        # Create subscription record
        subscription_doc = {
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
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "metadata": sub_data.metadata,
        }

        result = await subscriptions_collection.insert_one(subscription_doc)
        if not result.inserted_id:
            raise Exception("Failed to create subscription record")

        # Track subscription activation in PostHog
        if user_email:
            track_subscription_event(
                user_id=user_email,
                event_type=AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
                subscription_id=sub_data.subscription_id,
                plan_name="Pro",
                amount=sub_data.recurring_pre_tax_amount / 100
                if sub_data.recurring_pre_tax_amount
                else None,
                currency=sub_data.currency,
            )

        # Send welcome email
        await self._send_welcome_email(user_id)

        logger.info(f"Subscription activated: {sub_data.subscription_id}")
        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Subscription activated",
            subscription_id=sub_data.subscription_id,
        )

    async def _handle_subscription_renewed(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle subscription renewal."""
        sub_data = event.get_subscription_data()
        if not sub_data:
            raise ValueError("Invalid subscription data")

        # Update subscription billing dates
        result = await subscriptions_collection.update_one(
            {"dodo_subscription_id": sub_data.subscription_id},
            {
                "$set": {
                    "status": "active",
                    "next_billing_date": sub_data.next_billing_date,
                    "previous_billing_date": sub_data.previous_billing_date,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.matched_count == 0:
            logger.warning(
                f"Subscription not found for renewal: {sub_data.subscription_id}"
            )
        else:
            # Track subscription renewal in PostHog
            user_email = sub_data.customer.email if sub_data.customer else None
            if user_email:
                track_subscription_event(
                    user_id=user_email,
                    event_type=AnalyticsEvents.SUBSCRIPTION_RENEWED,
                    subscription_id=sub_data.subscription_id,
                    currency=sub_data.currency,
                )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Subscription renewed",
            subscription_id=sub_data.subscription_id,
        )

    async def _handle_subscription_cancelled(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle subscription cancellation."""
        sub_data = event.get_subscription_data()
        if not sub_data:
            raise ValueError("Invalid subscription data")

        update_data = {
            "status": "cancelled",
            "updated_at": datetime.now(timezone.utc),
        }

        if sub_data.cancelled_at:
            update_data["cancelled_at"] = sub_data.cancelled_at

        await subscriptions_collection.update_one(
            {"dodo_subscription_id": sub_data.subscription_id},
            {"$set": update_data},
        )

        # Track subscription cancellation in PostHog
        user_email = sub_data.customer.email if sub_data.customer else None
        if user_email:
            track_subscription_event(
                user_id=user_email,
                event_type=AnalyticsEvents.SUBSCRIPTION_CANCELLED,
                subscription_id=sub_data.subscription_id,
            )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Subscription cancelled",
            subscription_id=sub_data.subscription_id,
        )

    async def _handle_subscription_expired(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle subscription expiration."""
        sub_data = event.get_subscription_data()
        if not sub_data:
            raise ValueError("Invalid subscription data")

        await subscriptions_collection.update_one(
            {"dodo_subscription_id": sub_data.subscription_id},
            {
                "$set": {
                    "status": "expired",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        # Track subscription expiration in PostHog
        user_email = sub_data.customer.email if sub_data.customer else None
        if user_email:
            track_subscription_event(
                user_id=user_email,
                event_type=AnalyticsEvents.SUBSCRIPTION_EXPIRED,
                subscription_id=sub_data.subscription_id,
            )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Subscription expired",
            subscription_id=sub_data.subscription_id,
        )

    async def _handle_subscription_failed(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle subscription failure."""
        sub_data = event.get_subscription_data()
        if not sub_data:
            raise ValueError("Invalid subscription data")

        await subscriptions_collection.update_one(
            {"dodo_subscription_id": sub_data.subscription_id},
            {
                "$set": {
                    "status": "failed",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Subscription failed",
            subscription_id=sub_data.subscription_id,
        )

    async def _handle_subscription_on_hold(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle subscription on hold."""
        sub_data = event.get_subscription_data()
        if not sub_data:
            raise ValueError("Invalid subscription data")

        await subscriptions_collection.update_one(
            {"dodo_subscription_id": sub_data.subscription_id},
            {
                "$set": {
                    "status": "on_hold",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Subscription on hold",
            subscription_id=sub_data.subscription_id,
        )

    async def _handle_subscription_plan_changed(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle subscription plan change."""
        sub_data = event.get_subscription_data()
        if not sub_data:
            raise ValueError("Invalid subscription data")

        await subscriptions_collection.update_one(
            {"dodo_subscription_id": sub_data.subscription_id},
            {
                "$set": {
                    "product_id": sub_data.product_id,
                    "quantity": sub_data.quantity,
                    "recurring_pre_tax_amount": sub_data.recurring_pre_tax_amount,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Subscription plan changed",
            subscription_id=sub_data.subscription_id,
        )

    async def _send_welcome_email(self, user_id: str) -> None:
        """Send welcome email for new subscription."""
        try:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user and user.get("email"):
                await send_pro_subscription_email(
                    user_name=user.get("first_name", "User"),
                    user_email=user["email"],
                )
                logger.info(f"Welcome email sent to {user['email']}")
        except Exception as e:
            logger.error(f"Failed to send welcome email: {e}")


# Single instance
payment_webhook_service = PaymentWebhookService()
