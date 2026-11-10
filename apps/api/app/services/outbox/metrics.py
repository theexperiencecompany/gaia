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
