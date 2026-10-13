"""Time saved: what GAIA did for a user over the last week, from the rollups it already keeps."""

import asyncio
from datetime import UTC, datetime

from app.constants.time_saved import (
    MINUTES_SAVED_PER_ACTION,
    MINUTES_SAVED_PER_WORKFLOW_RUN,
    TIME_SAVED_WINDOW,
)
from app.db.repositories.usage_daily import usage_daily_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.schemas.usage import TimeSavedSummary


async def get_time_saved(user_id: str, now: datetime) -> TimeSavedSummary:
    """Summarize the seven full UTC days before now's day; counts are recorded, minutes estimated."""
    window_end = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = window_end - TIME_SAVED_WINDOW
    # usage_daily keys rows by UTC day as YYYY-MM-DD, which isoformat() of a date is.
    first_day, end_day = window_start.date().isoformat(), window_end.date().isoformat()
    daily_counts, workflow_runs = await asyncio.gather(
        usage_daily_repository.counts_since(user_id, first_day),
        workflow_executions_repository.count_succeeded_between(user_id, window_start, window_end),
    )
    actions = sum(count for day, count in daily_counts.items() if day < end_day)
    return TimeSavedSummary(
        window_start=window_start,
        window_end=window_end,
        actions=actions,
        workflow_runs=workflow_runs,
        minutes_saved=actions * MINUTES_SAVED_PER_ACTION
        + workflow_runs * MINUTES_SAVED_PER_WORKFLOW_RUN,
    )
