"""Constants for delivery-failure alerting.

Every message a user should have received and did not is reported once and grouped
into Slack incidents.

The bots read DeliveryFailureKind from the generated API types, so renaming a value
here fails their type-check rather than their reports.
"""

from __future__ import annotations

from enum import StrEnum


class DeliveryFailureKind(StrEnum):
    """Where in the pipeline a message was lost."""

    #: The platform accepted the send, then reported it undeliverable (WhatsApp status webhook).
    PLATFORM_REJECTED = "platform_rejected"
    #: The bot's platform send threw and the message was dead-lettered.
    SEND_FAILED = "send_failed"
    #: The outbound envelope was unusable (unparseable, invalid, empty), so nothing was sent.
    ENVELOPE_REJECTED = "envelope_rejected"
    #: A live chat turn or command failed; the user got an error notice instead of a reply.
    REPLY_FAILED = "reply_failed"
    #: The API could not publish the message to the bot's queue.
    ENQUEUE_FAILED = "enqueue_failed"
    #: The broker dead-lettered the message before any bot handled it (TTL, queue length).
    EXPIRED = "expired"


#: What a Slack incident says for each kind, after the platform name.
DELIVERY_FAILURE_KIND_LABELS: dict[DeliveryFailureKind, str] = {
    DeliveryFailureKind.PLATFORM_REJECTED: "platform rejected the message",
    DeliveryFailureKind.SEND_FAILED: "send failed",
    DeliveryFailureKind.ENVELOPE_REJECTED: "message was malformed",
    DeliveryFailureKind.REPLY_FAILED: "reply failed",
    DeliveryFailureKind.ENQUEUE_FAILED: "could not queue the message",
    DeliveryFailureKind.EXPIRED: "message expired in the queue",
}

#: Cap on queueing one alert from a delivery path, so a stalled Redis cannot hold it.
DELIVERY_FAILURE_QUEUE_TIMEOUT_SECONDS = 5.0

#: ARQ task names; the worker registers each under its constant.
RECORD_DELIVERY_FAILURE_TASK = "record_delivery_failure"
REFRESH_DELIVERY_INCIDENT_TASK = "refresh_delivery_incident"

#: An incident stays open while failures keep arriving; this much silence closes it,
#: and the next failure with the same fingerprint opens a new Slack message.
DELIVERY_INCIDENT_QUIET_SECONDS = 30 * 60
#: The parent message is re-rendered at most once per bucket, at the bucket's end.
DELIVERY_INCIDENT_REFRESH_SECONDS = 30
#: Occurrences posted individually in an incident's thread; the rest are only counted.
DELIVERY_INCIDENT_THREAD_LIMIT = 20
#: The incident lock's timing (DistributedLock): one failure holds it across its
#: Slack calls, which retry rate limits, so the hold cap is generous.
DELIVERY_INCIDENT_LOCK_LEASE_SECONDS = 30.0
DELIVERY_INCIDENT_LOCK_RENEW_SECONDS = 10.0
DELIVERY_INCIDENT_LOCK_MAX_HOLD_SECONDS = 120.0
DELIVERY_INCIDENT_LOCK_ACQUIRE_SECONDS = 60.0

DELIVERY_INCIDENT_KEY_PREFIX = "delivery_alerts:incident:"
REFRESH_JOB_ID_TEMPLATE = "delivery_alerts:refresh:{fingerprint}:{bucket}"

#: Durable copy queue bound to the outbound DLX; the DLQs themselves stay untouched
#: for manual replay.
DEAD_LETTER_TAP_QUEUE = "delivery_alerts.dead_letters"
#: The x-death reason a bot's own nack produces; those failures are reported by the bot.
DEAD_LETTER_REASON_REJECTED = "rejected"
DEAD_LETTER_TAP_PREFETCH = 10
DEAD_LETTER_TAP_RECONNECT_MAX_SECONDS = 30.0
#: Pause before requeueing a tap copy whose alert could not be queued (Redis down).
DEAD_LETTER_TAP_REQUEUE_DELAY_SECONDS = 5.0
DEAD_LETTER_TAP_CTX_KEY = "dead_letter_tap"
