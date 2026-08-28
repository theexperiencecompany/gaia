"""
Clean payment webhook service for Dodo Payments integration.
Handles webhook events and updates database state accordingly.
"""

from datetime import UTC, datetime
from typing import Any

from standardwebhooks.webhooks import Webhook

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.db.repositories.processed_webhooks import processed_webhook_repository
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.models.payment_models import SubscriptionDocument, SubscriptionUpdate
from app.models.webhook_models import (
    DodoWebhookEvent,
    DodoWebhookEventType,
    DodoWebhookProcessingResult,
)
from app.services.account_fs import schedule_account_sync
from app.services.analytics_service import (
    AnalyticsEvents,
    track_payment_event,
    track_subscription_event,
)
from app.services.email import send_pro_subscription_email
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log


class PaymentWebhookService:
    """Clean service for handling Dodo payment webhooks."""

    def __init__(self) -> None:
        self.webhook_secret = settings.DODO_WEBHOOK_PAYMENTS_SECRET
        # Initialize Standard Webhooks verifier
        if self.webhook_secret:
            try:
                # The secret should be base64 encoded for Standard Webhooks
                self.webhook_verifier = Webhook(self.webhook_secret)
            except Exception as e:
                log.error(
                    f"{LogTag.PAYMENT} Failed to initialize webhook verifier",
                    error=str(e),
                    error_type=type(e).__name__,
                )
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

    def verify_webhook_signature(self, payload: str, headers: dict[str, str]) -> bool:
        """
        Verify webhook signature using Standard Webhooks library.

        Args:
            payload: The raw JSON payload as string
            headers: Dictionary of headers from the webhook request
        """
        if not self.webhook_verifier:
            log.error(f"{LogTag.PAYMENT} No webhook verifier configured - rejecting webhook")
            return False

        try:
            log.info(
                f"{LogTag.PAYMENT} Verifying webhook signature using Standard Webhooks library"
            )

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

            log.info(f"{LogTag.PAYMENT} Webhook signature verification successful!")
            return True

        except Exception as e:
            log.warning(
                f"{LogTag.PAYMENT} Webhook signature verification failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def _is_webhook_processed(self, webhook_id: str) -> bool:
        """Check if webhook has already been processed."""
        return await processed_webhook_repository.is_processed(webhook_id)

    async def _mark_webhook_as_processed(
        self, webhook_id: str, event_type: str, result: DodoWebhookProcessingResult
    ) -> None:
        """Store webhook ID as processed in database."""
        try:
            await processed_webhook_repository.mark_processed(
                webhook_id,
                event_type=event_type,
                status=result.status,
                message=result.message,
                payment_id=result.payment_id,
                subscription_id=result.subscription_id,
            )
        except Exception as e:
            log.error(
                f"{LogTag.PAYMENT} Failed to store processed webhook ID",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def process_webhook(
        self, webhook_data: dict[str, Any], webhook_id: str
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
            event_type_raw = webhook_data.get("type", "unknown")
            # Extract financial fields from the nested payload (Dodo wraps data under "data")
            payload_data: dict[str, Any] = webhook_data.get("data", webhook_data)
            customer_field = payload_data.get("customer")
            customer_id = (
                customer_field.get("customer_id")
                if isinstance(customer_field, dict)
                else payload_data.get("customer_id")
            )
            log.set(
                payment={
                    "event_type": event_type_raw,
                    "status": "processing",
                    "webhook_id": webhook_id,
                    "customer_id": customer_id,
                    "amount_cents": payload_data.get("amount")
                    or payload_data.get("amount_paid")
                    or payload_data.get("total_amount", 0),
                    "currency": payload_data.get("currency", "usd"),
                }
            )

            # Check if webhook has already been processed
            if await self._is_webhook_processed(webhook_id):
                log.info(
                    f"{LogTag.PAYMENT} Webhook already processed, skipping", webhook_id=webhook_id
                )
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
            log.info(f"{LogTag.PAYMENT} Webhook processed", type=event.type, status=result.status)

            # Bust the cached plan tier so a plan change applies immediately.
            if result.subscription_id:
                await payment_service.invalidate_plan_cache_by_dodo_id(result.subscription_id)

            # Keep the workspace's account/subscription projection honest after
            # any billing state change.
            if result.status == "processed":
                metadata = payload_data.get("metadata")
                webhook_user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
                if isinstance(webhook_user_id, str) and webhook_user_id:
                    schedule_account_sync(webhook_user_id)

            # Store webhook as processed after successful handler execution
            await self._mark_webhook_as_processed(webhook_id, event.type.value, result)
            return result

        except Exception as e:
            log.error(
                f"{LogTag.PAYMENT} Webhook processing failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return DodoWebhookProcessingResult(
                event_type=webhook_data.get("type", "unknown"),
                status="failed",
                message=f"Processing error: {e!s}",
            )

    async def _get_user_id_from_metadata(self, metadata: dict[str, Any]) -> str | None:
        """Get the stable application user ID from payment metadata."""
        user_id = metadata.get("user_id")
        return str(user_id) if user_id else None

    # Payment event handlers
    async def _handle_payment_succeeded(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle successful payment - just log, subscription activation handles the rest."""
        payment_data = event.get_payment_data()
        if not payment_data:
            raise ValueError("Invalid payment data")

        log.info(f"{LogTag.PAYMENT} Payment succeeded", payment_id=payment_data.payment_id)

        # Track payment success in PostHog
        user_id = await self._get_user_id_from_metadata(payment_data.metadata)
        if user_id:
            track_payment_event(
                user_id=user_id,
                event_type=AnalyticsEvents.PAYMENT_SUCCEEDED,
                payment_id=payment_data.payment_id,
                amount=payment_data.total_amount / 100 if payment_data.total_amount else None,
                currency=payment_data.currency,
            )

        return DodoWebhookProcessingResult(
            event_type=event.type.value,
            status="processed",
            message="Payment success logged",
            payment_id=payment_data.payment_id,
            subscription_id=payment_data.subscription_id,
        )

    async def _handle_payment_failed(self, event: DodoWebhookEvent) -> DodoWebhookProcessingResult:
        """Handle failed payment."""
        payment_data = event.get_payment_data()
        if not payment_data:
            raise ValueError("Invalid payment data")

        log.warning(f"{LogTag.PAYMENT} Payment failed", payment_id=payment_data.payment_id)

        # Track payment failure in PostHog
        user_id = await self._get_user_id_from_metadata(payment_data.metadata)
        if user_id:
            track_payment_event(
                user_id=user_id,
                event_type=AnalyticsEvents.PAYMENT_FAILED,
                payment_id=payment_data.payment_id,
                amount=payment_data.total_amount / 100 if payment_data.total_amount else None,
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
        existing = await subscription_repository.get_by_dodo_id(sub_data.subscription_id)

        if existing:
            log.info(
                f"{LogTag.PAYMENT} Subscription already exists",
                subscription_id=sub_data.subscription_id,
            )
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
            user = await user_repository.get_by_email(user_email)
            if not user:
                log.error(
                    f"{LogTag.PAYMENT} User not found for subscription",
                    subscription_id=sub_data.subscription_id,
                )
                return DodoWebhookProcessingResult(
                    event_type=event.type.value,
                    status="failed",
                    message="User not found",
                    subscription_id=sub_data.subscription_id,
                )
            user_id = str(user.id)

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
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "metadata": sub_data.metadata,
        }

        await subscription_repository.create(SubscriptionDocument.model_validate(subscription_doc))

        # Track subscription activation in PostHog
        if user_id:
            track_subscription_event(
                user_id=user_id,
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

        log.info(
            f"{LogTag.PAYMENT} Subscription activated", subscription_id=sub_data.subscription_id
        )
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

        # Set each billing date only when the event carries one. Passing it
        # marks the field in model_fields_set even when None, and the repository
        # applies model_dump(exclude_unset=True) as $set — so an event that omits
        # a date would otherwise write null over the stored value.
        update = SubscriptionUpdate(status="active")
        if sub_data.next_billing_date is not None:
            update.next_billing_date = sub_data.next_billing_date
        if sub_data.previous_billing_date is not None:
            update.previous_billing_date = sub_data.previous_billing_date

        matched = await subscription_repository.apply_update_by_dodo_id(
            sub_data.subscription_id, update
        )

        if not matched:
            log.warning(
                f"{LogTag.PAYMENT} Subscription not found for renewal",
                subscription_id=sub_data.subscription_id,
            )
        else:
            # Track subscription renewal in PostHog
            user_id = await subscription_repository.get_user_id_by_dodo_id(sub_data.subscription_id)
            if user_id:
                track_subscription_event(
                    user_id=user_id,
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

        # A cancel scheduled for the end of the billing period
        # (cancel_at_next_billing_date=True) keeps the subscription active —
        # and the user on Pro — until the period ends. Status is deliberately
        # left untouched in that case: Dodo's documented payload for a
        # scheduled cancel reports status "active", but trusting the payload's
        # status would downgrade the user early if a future Dodo change ever
        # reported "cancelled" there. Only the `subscription.expired` event
        # flips status. An immediate cancellation (flag false) sets it now.
        update = SubscriptionUpdate(
            cancel_at_next_billing_date=sub_data.cancel_at_next_billing_date
        )
        if not sub_data.cancel_at_next_billing_date:
            update.status = "cancelled"
        # cancelled_at is only set when Dodo supplied one — leaving it unset keeps
        # it out of the $set rather than writing null over a stored value.
        if sub_data.cancelled_at:
            update.cancelled_at = sub_data.cancelled_at

        matched = await subscription_repository.apply_update_by_dodo_id(
            sub_data.subscription_id, update
        )
        if not matched:
            # No local row matched the Dodo id — returning failed (not
            # processed) keeps the webhook unacknowledged so Dodo retries and
            # the state can still be reconciled instead of being lost forever.
            log.error(
                f"{LogTag.PAYMENT} Subscription not found for cancellation",
                subscription_id=sub_data.subscription_id,
            )
            return DodoWebhookProcessingResult(
                event_type=event.type.value,
                status="failed",
                message="Subscription not found",
                subscription_id=sub_data.subscription_id,
            )

        # Track subscription cancellation in PostHog
        user_id = await subscription_repository.get_user_id_by_dodo_id(sub_data.subscription_id)
        if user_id:
            track_subscription_event(
                user_id=user_id,
                event_type=AnalyticsEvents.SUBSCRIPTION_CANCELLED,
                subscription_id=sub_data.subscription_id,
                properties={
                    "product_id": sub_data.product_id,
                    "billing_interval": sub_data.payment_frequency_interval,
                },
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

        await subscription_repository.apply_update_by_dodo_id(
            sub_data.subscription_id, SubscriptionUpdate(status="expired")
        )

        # Track subscription expiration in PostHog
        user_id = await subscription_repository.get_user_id_by_dodo_id(sub_data.subscription_id)
        if user_id:
            track_subscription_event(
                user_id=user_id,
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

        await subscription_repository.apply_update_by_dodo_id(
            sub_data.subscription_id, SubscriptionUpdate(status="failed")
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

        await subscription_repository.apply_update_by_dodo_id(
            sub_data.subscription_id, SubscriptionUpdate(status="on_hold")
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

        await subscription_repository.apply_update_by_dodo_id(
            sub_data.subscription_id,
            SubscriptionUpdate(
                product_id=sub_data.product_id,
                quantity=sub_data.quantity,
                recurring_pre_tax_amount=sub_data.recurring_pre_tax_amount,
            ),
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


# Single instance
payment_webhook_service = PaymentWebhookService()
