"""Unit tests for app.workers.tasks.usage_badge_tasks.

The daily cron that recomputes every user's activity tier and emails first-time
promotions. The task body is a thin wrapper: it runs ``sync_activity_tiers``
with emails on, drops the stats on the worker wide event, and returns the
summary string — the only operator-visible signal that the sweep ran. All
semantics (thresholds, monotonic promotion, idempotency) live in the service
and are its own tests' job; here we pin the wrapper's contract.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.usage_badge_tasks import promote_usage_badges
from tests.helpers import WideEventRecorder

MODULE = "app.workers.tasks.usage_badge_tasks"


class TestPromoteUsageBadges:
    async def test_runs_the_sweep_with_emails_and_returns_the_summary(self) -> None:
        sync = AsyncMock(return_value={"scanned": 12, "promoted": 3, "emailed": 3})
        with patch(f"{MODULE}.sync_activity_tiers", sync):
            result = await promote_usage_badges({})

        assert result == "Scanned 12 users, 3 promoted, 3 badge emails sent"
        sync.assert_awaited_once_with(send_emails=True)

    async def test_promotion_without_email_is_reflected_in_the_summary(self) -> None:
        with patch(
            f"{MODULE}.sync_activity_tiers",
            AsyncMock(return_value={"scanned": 5, "promoted": 4, "emailed": 2}),
        ):
            result = await promote_usage_badges({})

        assert result == "Scanned 5 users, 4 promoted, 2 badge emails sent"

    async def test_empty_sweep_returns_zero_counts(self) -> None:
        with patch(
            f"{MODULE}.sync_activity_tiers",
            AsyncMock(return_value={"scanned": 0, "promoted": 0, "emailed": 0}),
        ):
            result = await promote_usage_badges({})

        assert result == "Scanned 0 users, 0 promoted, 0 badge emails sent"

    async def test_stats_land_on_the_worker_wide_event(self) -> None:
        recorder = WideEventRecorder()
        with (
            patch("shared.py.wide_events._loguru", recorder),
            patch(
                f"{MODULE}.sync_activity_tiers",
                AsyncMock(return_value={"scanned": 12, "promoted": 3, "emailed": 3}),
            ),
        ):
            await promote_usage_badges({})

        assert len(recorder.events) == 1
        event = recorder.events[0]
        assert event["task"] == "promote_usage_badges"
        assert event["outcome"] == "success"
        assert event["scanned"] == 12
        assert event["promoted"] == 3
        assert event["emailed"] == 3

    async def test_service_failure_propagates_and_the_event_records_it(self) -> None:
        recorder = WideEventRecorder()
        with (
            patch("shared.py.wide_events._loguru", recorder),
            patch(
                f"{MODULE}.sync_activity_tiers",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
        ):
            with pytest.raises(RuntimeError, match="mongo down"):
                await promote_usage_badges({})

        event = recorder.events[0]
        assert event["task"] == "promote_usage_badges"
        assert event["outcome"] == "failed"
        assert event["final_level"] == "ERROR"
        assert event["errors"][0]["error"] == "mongo down"
        assert event["errors"][0]["error_type"] == "RuntimeError"
