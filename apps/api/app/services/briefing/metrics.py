"""Count every briefing run by its kind and how it ended, the signal the briefing alerts read.

A run that raised is FAILED; every other run ends in a BriefingRunOutcome. Every series is
created at zero when the worker serves metrics, so the first failure after a restart is an
increase increase() can see.
"""

from collections.abc import Awaitable
from typing import Final

from prometheus_client import Counter

from app.constants.briefing import BriefingKind, BriefingRunOutcome
from app.services.storage.metrics import _register_once
from shared.py.wide_events import log

#: The outcome label of a run that raised before it could end.
FAILED: Final = "failed"

BRIEF_RUN_TOTAL = _register_once(
    "gaia_brief_run_total",
    lambda: Counter(
        name="gaia_brief_run_total",
        documentation="Briefing runs by kind and how each ended; failed is a run that raised",
        labelnames=("kind", "outcome"),
    ),
)


async def counted_run(kind: BriefingKind, run: Awaitable[BriefingRunOutcome]) -> BriefingRunOutcome:
    """Await one briefing run, counting how it ended and recording it on the wide event."""
    try:
        outcome = await run
    except Exception:
        BRIEF_RUN_TOTAL.labels(kind, FAILED).inc()
        log.set_ns("briefing", outcome=FAILED)
        raise
    BRIEF_RUN_TOTAL.labels(kind, outcome.value).inc()
    log.set_ns("briefing", outcome=outcome.value)
    return outcome


def create_brief_run_series() -> None:
    """Create every briefing run series at zero, so its first increment is visible."""
    for kind in BriefingKind:
        for outcome in [*(o.value for o in BriefingRunOutcome), FAILED]:
            BRIEF_RUN_TOTAL.labels(kind, outcome)
