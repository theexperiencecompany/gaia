"""Count every Dodo webhook delivery by what GAIA did with it, the signal the payment alerts read.

processed, ignored, failed and abandoned are the processing result's own values; invalid_signature
is a delivery that did not verify, error one that raised before it had a result. Every series is
created at zero when the API starts, so the first failure after a restart is an increase.
"""

from enum import StrEnum

from prometheus_client import Counter

from app.models.webhook_models import WebhookProcessingStatus
from app.utils.prometheus_registry import register_once


class PaymentWebhookRejection(StrEnum):
    """A delivery that never reached a processing result."""

    INVALID_SIGNATURE = "invalid_signature"
    ERROR = "error"


PAYMENT_WEBHOOK_TOTAL = register_once(
    "gaia_payment_webhook_total",
    lambda: Counter(
        name="gaia_payment_webhook_total",
        documentation="Dodo webhook deliveries by outcome; failed and abandoned are paid events GAIA could not apply",
        labelnames=("outcome",),
    ),
)


def observe_payment_webhook(outcome: WebhookProcessingStatus | PaymentWebhookRejection) -> None:
    """Count one webhook delivery by how it ended."""
    PAYMENT_WEBHOOK_TOTAL.labels(outcome).inc()


def create_payment_webhook_series() -> None:
    """Create every payment-webhook series at zero, so its first increment is visible."""
    for outcome in (*WebhookProcessingStatus, *PaymentWebhookRejection):
        PAYMENT_WEBHOOK_TOTAL.labels(outcome)
