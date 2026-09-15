"""
Clean payment webhook service for Dodo Payments integration.
Handles webhook events and updates database state accordingly.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from standardwebhooks.webhooks import Webhook

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.payments import WEBHOOK_ROW_WAIT_MAX
from app.db.repositories.processed_webhooks import processed_webhook_repository
from app.models.payment_models import ProcessedWebhookUpdate
from app.models.webhook_models import (
    DodoPaymentData,
    DodoWebhookEvent,
    DodoWebhookEventType,
    DodoWebhookProcessingResult,
    WebhookProcessingStatus,
)
from app.services.account_fs import schedule_account_sync
from app.services.analytics_service import AnalyticsEvents, track_payment_event
from app.services.payments.subscription_events import (
    CENTS_PER_UNIT,
    SubscriptionEvent,
    SubscriptionEventKind,
    SubscriptionEventOutcome,
    apply_subscription_event,
)
from shared.py.wide_events import log

WebhookHandler = Callable[[DodoWebhookEvent], Awaitable[DodoWebhookProcessingResult]]

# The subscription events GAIA acts on, and what each one reports.
SUBSCRIPTION_EVENT_KINDS: dict[DodoWebhookEventType, SubscriptionEventKind] = {
    DodoWebhookEventType.SUBSCRIPTION_ACTIVE: SubscriptionEventKind.ACTIVATED,
    DodoWebhookEventType.SUBSCRIPTION_RENEWED: SubscriptionEventKind.RENEWED,
    DodoWebhookEventType.SUBSCRIPTION_CANCELLED: SubscriptionEventKind.CANCELLED,
    DodoWebhookEventType.SUBSCRIPTION_EXPIRED: SubscriptionEventKind.EXPIRED,
    DodoWebhookEventType.SUBSCRIPTION_FAILED: SubscriptionEventKind.FAILED,
    DodoWebhookEventType.SUBSCRIPTION_ON_HOLD: SubscriptionEventKind.ON_HOLD,
    DodoWebhookEventType.SUBSCRIPTION_PLAN_CHANGED: SubscriptionEventKind.PLAN_CHANGED,
}

# The message is the only thing distinguishing what a delivery did in Dodo's
# dashboard and in GAIA's own webhook log.
SUBSCRIPTION_APPLIED_MESSAGES: dict[SubscriptionEventKind, str] = {
    SubscriptionEventKind.ACTIVATED: "Subscription activated",
    SubscriptionEventKind.RENEWED: "Subscription renewed",
    SubscriptionEventKind.CANCELLED: "Subscription cancelled",
    SubscriptionEventKind.EXPIRED: "Subscription expired",
    SubscriptionEventKind.FAILED: "Subscription failed",
    SubscriptionEventKind.ON_HOLD: "Subscription on hold",
    SubscriptionEventKind.PLAN_CHANGED: "Subscription plan changed",
}


def _outcome_of(result: DodoWebhookProcessingResult) -> ProcessedWebhookUpdate:
    return ProcessedWebhookUpdate(
        status=result.status,
        message=result.message,
        payment_id=result.payment_id,
        subscription_id=result.subscription_id,
    )


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

        self.handlers: dict[DodoWebhookEventType, WebhookHandler] = {
            DodoWebhookEventType.PAYMENT_SUCCEEDED: self._handle_payment_succeeded,
            DodoWebhookEventType.PAYMENT_FAILED: self._handle_payment_failed,
            DodoWebhookEventType.PAYMENT_PROCESSING: self._handle_payment_processing,
            DodoWebhookEventType.PAYMENT_CANCELLED: self._handle_payment_cancelled,
            **dict.fromkeys(SUBSCRIPTION_EVENT_KINDS, self._handle_subscription_event),
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

    async def process_webhook(
        self, webhook_data: dict[str, Any], webhook_id: str
    ) -> DodoWebhookProcessingResult:
        """
        Process a Dodo payment webhook exactly once.

        The delivery is claimed (inserted under the unique ``webhook_id``)
        before its handler runs, so a replay or a racing duplicate is turned
        away at the claim, never after the side effects. A handler failure —
        raised or returned — releases the claim so Dodo's retry is a clean run;
        only a processed or ignored delivery keeps it.

        Args:
            webhook_data: The webhook payload
            webhook_id: Unique webhook ID from webhook-id header for idempotency

        Returns:
            Processing result
        """
        event_type_raw = str(webhook_data.get("type", "unknown"))
        if not await processed_webhook_repository.claim(webhook_id, event_type=event_type_raw):
            log.info(f"{LogTag.PAYMENT} Webhook already processed, skipping", webhook_id=webhook_id)
            return DodoWebhookProcessingResult(
                event_type=event_type_raw,
                status=WebhookProcessingStatus.IGNORED,
                message="Webhook already processed",
            )
        try:
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

            event = DodoWebhookEvent(**webhook_data)

            handler = self._handler_for(event.type, webhook_id)
            if not handler:
                result = DodoWebhookProcessingResult(
                    event_type=event.type,
                    status=WebhookProcessingStatus.IGNORED,
                    message=f"No handler for {event.type}",
                )
                # The claim already blocks a replay; the outcome is for the record.
                await processed_webhook_repository.record_outcome(webhook_id, _outcome_of(result))
                return result

            result = await handler(event)
            log.info(f"{LogTag.PAYMENT} Webhook processed", type=event.type, status=result.status)

            if result.status == WebhookProcessingStatus.FAILED:
                # The handler ran and the state change still did not land, so
                # this delivery is unfinished. Recording the outcome would keep
                # the claim and the endpoint would answer 200 — between them
                # that ends the event's life: Dodo stops resending and a manual
                # redelivery is refused as a replay. Hand the claim back and let
                # the endpoint ask for a retry.
                log.error(
                    f"{LogTag.PAYMENT} Webhook handler did not complete; releasing the claim",
                    webhook_id=webhook_id,
                    event_type=event.type,
                    failure_reason=result.message,
                )
                await processed_webhook_repository.release(webhook_id)
                return result

            if result.status == WebhookProcessingStatus.ABANDONED:
                # No retry can land this one. The endpoint acknowledges it so
                # Dodo stops redelivering; the claim is released so a human can
                # redeliver it by hand once the cause (a missing user, a row
                # that never came) is fixed, instead of being turned away as a
                # replay.
                log.error(
                    f"{LogTag.PAYMENT} Webhook abandoned; releasing the claim for manual redelivery",
                    webhook_id=webhook_id,
                    event_type=event.type,
                    failure_reason=result.message,
                )
                await processed_webhook_repository.release(webhook_id)
                return result

            # Keep the workspace's account/subscription projection honest after
            # any billing state change.
            if result.status == WebhookProcessingStatus.PROCESSED:
                metadata = payload_data.get("metadata")
                webhook_user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
                if isinstance(webhook_user_id, str) and webhook_user_id:
                    schedule_account_sync(webhook_user_id)

            await processed_webhook_repository.record_outcome(webhook_id, _outcome_of(result))
            return result

        except (ValidationError, ValueError) as e:
            # The body itself is the problem: it will not validate any better
            # on the retry Dodo would send for a failure.
            log.error(
                f"{LogTag.PAYMENT} Webhook payload rejected; abandoning the delivery",
                error=str(e),
                error_type=type(e).__name__,
                webhook_id=webhook_id,
            )
            await processed_webhook_repository.release(webhook_id)
            return DodoWebhookProcessingResult(
                event_type=event_type_raw,
                status=WebhookProcessingStatus.ABANDONED,
                message=f"Invalid payload: {e!s}",
            )
        except Exception as e:
            log.error(
                f"{LogTag.PAYMENT} Webhook processing failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            await processed_webhook_repository.release(webhook_id)
            return DodoWebhookProcessingResult(
                event_type=event_type_raw,
                status=WebhookProcessingStatus.FAILED,
                message=f"Processing error: {e!s}",
            )

    def _handler_for(self, event_type: str, webhook_id: str) -> WebhookHandler | None:
        """The handler for this type, if GAIA acts on it.

        Resolved through the enum so an event type Dodo added since is
        acknowledged and ignored — not rejected as a validation error the
        sender keeps retrying.
        """
        try:
            known = DodoWebhookEventType(event_type)
        except ValueError:
            log.warning(
                f"{LogTag.PAYMENT} Unlisted Dodo event type acknowledged and ignored",
                event_type=event_type,
                webhook_id=webhook_id,
            )
            return None
        return self.handlers.get(known)

    async def _get_user_id_from_metadata(self, metadata: dict[str, Any]) -> str | None:
        """Get the stable application user ID from payment metadata."""
        user_id = metadata.get("user_id")
        return str(user_id) if user_id else None

    async def _capture_payment(
        self, event_type: AnalyticsEvents, payment_data: DodoPaymentData
    ) -> None:
        """Capture a payment against the GAIA user who made it.

        A webhook has no authenticated request for the context to inherit, so
        the id has to come off the payment's own metadata. Without one the event
        would land on an anonymous profile and quietly split that person's
        funnel in two, so it is not sent at all — and the gap is logged, because
        a real payment with no event behind it is invisible in PostHog by
        definition.
        """
        user_id = await self._get_user_id_from_metadata(payment_data.metadata)
        if not user_id:
            log.warning(
                f"{LogTag.PAYMENT} Payment carries no GAIA user id; analytics not captured",
                failure_reason="unattributable_payment",
                analytics_event=event_type.value,
                payment_id=payment_data.payment_id,
            )
            return

        track_payment_event(
            user_id=user_id,
            event_type=event_type,
            payment_id=payment_data.payment_id,
            amount=payment_data.total_amount / CENTS_PER_UNIT
            if payment_data.total_amount
            else None,
            currency=payment_data.currency,
        )

    # Payment event handlers
    async def _handle_payment_succeeded(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Handle successful payment - just log, subscription activation handles the rest."""
        payment_data = event.get_payment_data()
        if not payment_data:
            raise ValueError("Invalid payment data")

        log.info(f"{LogTag.PAYMENT} Payment succeeded", payment_id=payment_data.payment_id)

        await self._capture_payment(AnalyticsEvents.PAYMENT_SUCCEEDED, payment_data)

        return DodoWebhookProcessingResult(
            event_type=event.type,
            status=WebhookProcessingStatus.PROCESSED,
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

        await self._capture_payment(AnalyticsEvents.PAYMENT_FAILED, payment_data)

        return DodoWebhookProcessingResult(
            event_type=event.type,
            status=WebhookProcessingStatus.PROCESSED,
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
            event_type=event.type,
            status=WebhookProcessingStatus.PROCESSED,
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
            event_type=event.type,
            status=WebhookProcessingStatus.PROCESSED,
            message="Payment cancellation noted",
            payment_id=payment_data.payment_id,
            subscription_id=payment_data.subscription_id,
        )

    # Subscription event handlers
    async def _handle_subscription_event(
        self, event: DodoWebhookEvent
    ) -> DodoWebhookProcessingResult:
        """Parse the payload and hand it to the reducer; it owns every write."""
        sub_data = event.get_subscription_data()
        if not sub_data:
            raise ValueError("Invalid subscription data")

        kind = SUBSCRIPTION_EVENT_KINDS[DodoWebhookEventType(event.type)]
        applied = await apply_subscription_event(
            SubscriptionEvent(kind=kind, occurred_at=event.occurred_at, data=sub_data)
        )
        status, message = self._reply_for(applied.outcome, event, kind)
        return DodoWebhookProcessingResult(
            event_type=event.type,
            status=status,
            message=message,
            subscription_id=sub_data.subscription_id,
        )

    @staticmethod
    def _reply_for(
        outcome: SubscriptionEventOutcome, event: DodoWebhookEvent, kind: SubscriptionEventKind
    ) -> tuple[WebhookProcessingStatus, str]:
        """What the delivery is owed for what the reducer did.

        A missing row is the one outcome whose answer depends on time:
        ``subscription.active`` is a separate delivery with its own retries,
        so a lifecycle event that beat it is asked to come back — but only for
        as long as the activation could plausibly still be on its way.
        """
        match outcome:
            case SubscriptionEventOutcome.CREATED:
                return WebhookProcessingStatus.PROCESSED, "Subscription activated"
            case SubscriptionEventOutcome.APPLIED:
                return WebhookProcessingStatus.PROCESSED, SUBSCRIPTION_APPLIED_MESSAGES[kind]
            case SubscriptionEventOutcome.UNCHANGED:
                return WebhookProcessingStatus.PROCESSED, "Subscription already in this state"
            case SubscriptionEventOutcome.STALE:
                return WebhookProcessingStatus.IGNORED, "Stale event"
            case SubscriptionEventOutcome.NO_OWNER:
                return WebhookProcessingStatus.ABANDONED, "User not found"
            case SubscriptionEventOutcome.NO_ROW:
                if datetime.now(UTC) - event.occurred_at > WEBHOOK_ROW_WAIT_MAX:
                    return WebhookProcessingStatus.ABANDONED, "Subscription not found"
                return WebhookProcessingStatus.FAILED, "Subscription not found"


# Single instance
payment_webhook_service = PaymentWebhookService()
