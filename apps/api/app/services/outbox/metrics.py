"""Outbox counters: the silent paths (a drop, a degraded compose) are never silent.

Labels are bounded enums, never ids.
"""

from prometheus_client import Counter

from app.services.storage.metrics import _register_once

OUTBOX_ITEMS_DROPPED = _register_once(
    "outbox_items_dropped_total",
    lambda: Counter(
        name="outbox_items_dropped_total",
        documentation="Outbox items recorded and never alerted, by reason",
        labelnames=("reason",),
    ),
)

OUTBOX_ITEMS_HELD = _register_once(
    "outbox_items_held_total",
    lambda: Counter(
        name="outbox_items_held_total",
        documentation="Outbox items held to be told later, by reason",
        labelnames=("reason",),
    ),
)

OUTBOX_ITEMS_FAILED = _register_once(
    "outbox_items_failed_total",
    lambda: Counter(
        name="outbox_items_failed_total",
        documentation="Outbox items that should have been told and were not, by reason",
        labelnames=("reason",),
    ),
)

OUTBOX_ATTACHMENTS_FAILED = _register_once(
    "outbox_attachments_failed_total",
    lambda: Counter(
        name="outbox_attachments_failed_total",
        documentation="Attachments the chat app's queue refused, whether or not their caption was told instead",
    ),
)

OUTBOX_TRANSPORT_RETRIES = _register_once(
    "outbox_transport_retries_total",
    lambda: Counter(
        name="outbox_transport_retries_total",
        documentation="Messages handed back to the queue because the chat apps' broker could not take them",
    ),
)

OUTBOX_SPOKEN_FAILED = _register_once(
    "outbox_spoken_failed_total",
    lambda: Counter(
        name="outbox_spoken_failed_total",
        documentation="Messages the user's live call did not take; they were still recorded and shown in the app",
    ),
)

OUTBOX_ITEMS_RECOVERED = _register_once(
    "outbox_items_recovered_total",
    lambda: Counter(
        name="outbox_items_recovered_total",
        documentation="Unsent items the recovery sweep drove again, by the state it found them in",
        labelnames=("state",),
    ),
)

OUTBOX_COMPOSE_DEGRADED = _register_once(
    "outbox_compose_degraded_total",
    lambda: Counter(
        name="outbox_compose_degraded_total",
        documentation="Messages sent as the plain degraded render because the composer broke the contract twice",
    ),
)

OUTBOX_JUDGE_DECIDED = _register_once(
    "outbox_judge_decided_total",
    lambda: Counter(
        name="outbox_judge_decided_total",
        documentation="Items the Judge decided, by the pass that decided them",
        labelnames=("decided_by",),
    ),
)

OUTBOX_JUDGE_UNAVAILABLE = _register_once(
    "outbox_judge_unavailable_total",
    lambda: Counter(
        name="outbox_judge_unavailable_total",
        documentation="Items decided without the Judge because both passes failed, by cause",
        labelnames=("cause",),
    ),
)

OUTBOX_JUDGE_INTERRUPT_CAPPED = _register_once(
    "outbox_judge_interrupt_capped_total",
    lambda: Counter(
        name="outbox_judge_interrupt_capped_total",
        documentation="Interrupts the Judge asked for that the daily cap refused",
    ),
)

OUTBOX_INTERNALS_LEAKED = _register_once(
    "outbox_internals_leaked_total",
    lambda: Counter(
        name="outbox_internals_leaked_total",
        documentation="Texts found naming GAIA internals, by where: a producer's facts or composed parts",
        labelnames=("where",),
    ),
)
