"""Workflow runs per day, from the executions store: the ones that succeeded and the ones that failed.

The briefing's own workflows are left out by the read; a run still going or skipped is
neither.
"""

from collections.abc import Sequence

from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE
from app.models.brief_pool_models import DataSeries
from app.models.workflow_execution_models import RunMoment, WorkflowExecutionStatus
from app.services.briefing.fact_pool.window import SeriesName, SeriesWindow, day_series, per_day

_RUN_SERIES: dict[WorkflowExecutionStatus, SeriesName] = {
    "success": SeriesName(
        id="workflows_succeeded",
        label="Workflow runs that succeeded",
        unit="runs",
        source=GAIA_SOURCE,
        app=GAIA_APP_NAME,
    ),
    "failed": SeriesName(
        id="workflows_failed",
        label="Workflow runs that failed",
        unit="runs",
        source=GAIA_SOURCE,
        app=GAIA_APP_NAME,
    ),
}


def run_series(runs: Sequence[RunMoment], window: SeriesWindow) -> list[DataSeries]:
    """Return the runs that succeeded and failed on each day; a series with none is left out."""
    found = (
        day_series(
            name, per_day([r.started_at for r in runs if r.status == status], window), window
        )
        for status, name in _RUN_SERIES.items()
    )
    return [series for series in found if series is not None]
