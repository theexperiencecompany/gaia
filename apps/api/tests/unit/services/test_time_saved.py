"""Time saved over the seven full UTC days before today, from the usage and workflow rollups."""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.schemas.usage import TimeSavedSummary
from app.services.time_saved import get_time_saved
from tests.helpers import local_timezone

MODULE = "app.services.time_saved"
USER_ID = "64a0000000000000000000a1"
IST = timezone(timedelta(hours=5, minutes=30))
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
        summary = await get_time_saved(USER_ID, datetime(2026, 10, 14, 15, 47, 12, tzinfo=IST))

    assert summary == TimeSavedSummary(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        actions=10,
        workflow_runs=3,
        minutes_saved=10 * 2 + 3 * 10,
    )
    counts.assert_awaited_once_with(USER_ID, "2026-10-07")
    runs.assert_awaited_once_with(USER_ID, WINDOW_START, WINDOW_END)


async def test_just_after_utc_midnight_the_window_is_the_week_that_just_ended() -> None:
    with (
        patch(
            f"{MODULE}.usage_daily_repository.counts_since",
            AsyncMock(return_value={"2026-10-13": 1}),
        ),
        patch(
            f"{MODULE}.workflow_executions_repository.count_succeeded_between",
            AsyncMock(return_value=0),
        ),
    ):
        summary = await get_time_saved(USER_ID, datetime(2026, 10, 14, 0, 0, 1, 5, tzinfo=UTC))

    assert (summary.window_start, summary.window_end) == (WINDOW_START, WINDOW_END)
    assert (summary.actions, summary.minutes_saved) == (1, 2)


async def test_the_day_boundary_is_utc_whatever_the_servers_zone() -> None:
    """20:00 UTC on the 13th is already the 14th in Kolkata; the window still ends at the 13th UTC."""
    with (
        patch(f"{MODULE}.usage_daily_repository.counts_since", AsyncMock(return_value={})),
        patch(
            f"{MODULE}.workflow_executions_repository.count_succeeded_between",
            AsyncMock(return_value=0),
        ),
        local_timezone("Asia/Kolkata"),
    ):
        summary = await get_time_saved(USER_ID, datetime(2026, 10, 13, 20, 0, tzinfo=UTC))

    assert summary.window_end == datetime(2026, 10, 13, tzinfo=UTC)
