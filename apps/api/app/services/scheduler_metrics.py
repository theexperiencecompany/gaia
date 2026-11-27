"""Count every scheduled task by how it ended, and how late it started: the scheduler alerts' signal.

failed is a fire that raised or reported failure; reaped is a task found wedged in EXECUTING and
reset. Lateness is the time between a task's scheduled time and the moment a worker claimed it.
Every series is created at zero when the API and the worker start serving metrics.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from prometheus_client import Counter, Histogram

from app.utils.prometheus_registry import register_once


class ScheduledTaskKind(StrEnum):
    """The domain whose scheduler ran the task."""

    REMINDER = "reminder"
    WORKFLOW = "workflow"


class ScheduledTaskOutcome(StrEnum):
    """How one fire of a scheduled task ended."""

    OK = "ok"
    FAILED = "failed"
    REAPED = "reaped"


#: Edges at the 1 and 5 minute lateness a reminder is felt at; the top is the stale-EXECUTING threshold.
_LATENESS_BUCKETS: Final[tuple[float, ...]] = (1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600)

SCHEDULED_TASK_TOTAL = register_once(
    "gaia_scheduled_task_total",
    lambda: Counter(
        name="gaia_scheduled_task_total",
        documentation="Scheduled task fires by kind and outcome; reaped is a task found stuck in EXECUTING",
        labelnames=("kind", "outcome"),
    ),
)

SCHEDULED_TASK_LATENESS_SECONDS = register_once(
    "gaia_scheduled_task_lateness_seconds",
    lambda: Histogram(
        name="gaia_scheduled_task_lateness_seconds",
        documentation="Scheduled time to the moment a worker claimed the task, in seconds",
        labelnames=("kind",),
        buckets=_LATENESS_BUCKETS,
    ),
)

ALL_SCHEDULER_COLLECTORS: Final[tuple[Counter | Histogram, ...]] = (
    SCHEDULED_TASK_TOTAL,
    SCHEDULED_TASK_LATENESS_SECONDS,
)


def observe_scheduled_fire(kind: ScheduledTaskKind, outcome: ScheduledTaskOutcome) -> None:
    """Count one fire of a scheduled task by how it ended."""
    SCHEDULED_TASK_TOTAL.labels(kind.value, outcome.value).inc()


def observe_claim_lateness(kind: ScheduledTaskKind, scheduled_at: datetime | None) -> None:
    """Record how long past its scheduled time a task was when a worker claimed it."""
    if scheduled_at is None:
        return
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    late = (datetime.now(UTC) - scheduled_at).total_seconds()
    SCHEDULED_TASK_LATENESS_SECONDS.labels(kind.value).observe(max(0.0, late))


def create_scheduled_task_series() -> None:
    """Create every scheduler series at zero, so its first increment is visible."""
    for kind in ScheduledTaskKind:
        SCHEDULED_TASK_LATENESS_SECONDS.labels(kind.value)
        for outcome in ScheduledTaskOutcome:
            SCHEDULED_TASK_TOTAL.labels(kind.value, outcome.value)
