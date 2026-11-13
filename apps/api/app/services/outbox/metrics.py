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

OUTBOX_ITEMS_FAILED = _register_once(
    "outbox_items_failed_total",
    lambda: Counter(
        name="outbox_items_failed_total",
        documentation="Outbox items that should have been told and were not, by reason",
        labelnames=("reason",),
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
