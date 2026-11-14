"""Time saved over the seven UTC days before a week end, from the usage and workflow rollups."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

from app.schemas.usage import TimeSavedSummary
from app.services.time_saved import get_time_saved

MODULE = "app.services.time_saved"
USER_ID = "64a0000000000000000000a1"
WINDOW_START = datetime(2026, 10, 7, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 14, tzinfo=UTC)


async def test_the_week_counts_actions_and_runs_and_estimates_the_minutes() -> None:
    daily = {"2026-10-07": 4, "2026-10-13": 6, "2026-10-14": 50}
    with (
        patch(
            f"{MODULE}.usage_daily_repository.counts_since", AsyncMock(return_value=daily)
        ) as counts,
        patch(
            f"{MODULE}.workflow_executions_repository.count_succeeded_between",
            AsyncMock(return_value=3),
        ) as runs,
    ):
        summary = await get_time_saved(USER_ID, date(2026, 10, 14))

    assert summary == TimeSavedSummary(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        actions=10,
        workflow_runs=3,
        minutes_saved=10 * 2 + 3 * 10,
    )
    counts.assert_awaited_once_with(USER_ID, "2026-10-07")
    runs.assert_awaited_once_with(USER_ID, WINDOW_START, WINDOW_END)
