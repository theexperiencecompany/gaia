"""Prometheus counter of how each scout's turn in a brief ended, the series the scout alert reads.

Both labels are closed sets: a ScoutOutcome, and a ScoutSkipReason or NO_SKIP. Every series
the alert reads exists at zero once the worker serves metrics, so the first failure after a
restart is an increase rather than a new series increase() cannot see.
"""

from typing import Final

from prometheus_client import Counter

from app.models.scout_models import ScoutOutcome, ScoutResult, ScoutSkipReason
from app.utils.prometheus_registry import register_once

#: The skip_reason label on a turn that was not skipped.
NO_SKIP: Final = "none"

SCOUT_TURN_TOTAL = register_once(
    "gaia_brief_scout_total",
    lambda: Counter(
        name="gaia_brief_scout_total",
        documentation="Brief scout turns by how they ended and, when skipped, why",
        labelnames=("outcome", "skip_reason"),
    ),
)

ALL_SCOUT_COLLECTORS: Final[tuple[Counter, ...]] = (SCOUT_TURN_TOTAL,)


def record_scout_turn(result: ScoutResult) -> None:
    """Count one scout's turn by its outcome and skip reason."""
    reason = result.skip_reason.value if result.skip_reason is not None else NO_SKIP
    SCOUT_TURN_TOTAL.labels(result.outcome.value, reason).inc()


def create_alerted_scout_series() -> None:
    """Create every series the scout alert reads, at zero."""
    for outcome in ScoutOutcome:
        if outcome is not ScoutOutcome.SKIPPED:
            SCOUT_TURN_TOTAL.labels(outcome.value, NO_SKIP)
    for reason in ScoutSkipReason:
        SCOUT_TURN_TOTAL.labels(ScoutOutcome.SKIPPED.value, reason.value)
