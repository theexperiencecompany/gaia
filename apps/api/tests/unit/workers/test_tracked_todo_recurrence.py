"""Unit tests for tracked_todo recurrence + timezone resolution.

Covers the recently-refactored timezone code paths in
app.workers.tasks.tracked_todo_tasks:

- _compute_next_run now evaluates cron in recurrence_tz via the
  canonical get_next_run_time, parsing the zone with Timezone.parse so a
  stored ±HH:MM offset no longer crashes ZoneInfo and silently falls
  back to UTC (the regression this fix closed).
- _load_user_with_tz resolves the user's home zone via Timezone.parse
  and falls back to Timezone.utc() on a missing user or exception.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.models.user_models import AuthenticatedUser
from app.utils.timezone import Timezone
from app.workers.tasks.tracked_todo_tasks import (
    _compute_next_run,
    _load_user_with_tz,
)


def _user_context(**fields: object) -> Callable[[str], AuthenticatedUser]:
    """Build the user load_user_context returns for whichever user id it is asked for."""
    return lambda user_id: AuthenticatedUser(user_id=user_id, **fields)


KOLKATA = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# _compute_next_run
# ---------------------------------------------------------------------------


class TestComputeNextRun:
    def test_offset_form_tz_does_not_crash_and_is_correct(self):
        """Regression: a stored +05:30 offset must resolve 9 AM IST to 03:30 UTC, not silently fall back to UTC."""
        next_run = _compute_next_run("0 9 * * *", "+05:30")
        assert next_run is not None
        assert next_run.tzinfo is not None
        assert next_run.hour == 3
        assert next_run.minute == 30

    def test_iana_tz_matches_offset_equivalent(self):
        """Asia/Kolkata is the IANA name for the +05:30 offset above."""
        next_run = _compute_next_run("0 9 * * *", "Asia/Kolkata")
        assert next_run is not None
        assert next_run.hour == 3
        assert next_run.minute == 30

    def test_no_tz_evaluates_in_utc(self):
        """No recurrence_tz -> cron interpreted in UTC, so 9 AM stays 09:00 UTC."""
        next_run = _compute_next_run("0 9 * * *", None)
        assert next_run is not None
        assert next_run.hour == 9
        assert next_run.minute == 0

    def test_interval_shortcut_is_roughly_now_plus_one_hour(self):
        before = datetime.now(UTC)
        next_run = _compute_next_run("every_1h")
        after = datetime.now(UTC)

        assert next_run is not None
        assert next_run.tzinfo is not None
        assert before + timedelta(hours=1) <= next_run <= after + timedelta(hours=1)

    def test_anchored_daily_preserves_local_time_of_day(self):
        """A past 08:00 IST anchor must recur strictly in the future, still reading as 08:00 in Asia/Kolkata."""
        anchor = datetime.now(KOLKATA).replace(
            hour=8, minute=0, second=0, microsecond=0
        ) - timedelta(days=3)

        next_run = _compute_next_run("daily", "Asia/Kolkata", anchor=anchor)

        assert next_run is not None
        assert next_run.tzinfo is not None
        assert next_run > datetime.now(UTC)

        local = next_run.astimezone(KOLKATA)
        assert local.hour == 8
        assert local.minute == 0

    def test_unrecognised_recurrence_returns_none(self):
        assert _compute_next_run("not-a-recurrence", "UTC") is None


# ---------------------------------------------------------------------------
# _load_user_with_tz
# ---------------------------------------------------------------------------


class TestLoadUserWithTz:
    async def test_offset_timezone_resolved(self):
        with patch(
            "app.workers.tasks.tracked_todo_tasks.load_user_context",
            new=AsyncMock(side_effect=_user_context(timezone="+05:30")),
        ):
            user_data, tz = await _load_user_with_tz("user1")

        assert isinstance(tz, Timezone)
        assert tz.value == "+05:30"
        assert user_data.user_id == "user1"

    async def test_iana_timezone_resolved(self):
        with patch(
            "app.workers.tasks.tracked_todo_tasks.load_user_context",
            new=AsyncMock(side_effect=_user_context(timezone="Asia/Kolkata")),
        ):
            _user_data, tz = await _load_user_with_tz("user1")

        assert tz.value == "Asia/Kolkata"

    async def test_missing_timezone_falls_back_to_utc(self):
        with patch(
            "app.workers.tasks.tracked_todo_tasks.load_user_context",
            new=AsyncMock(return_value={"name": "no-tz-user"}),
        ):
            user_data, tz = await _load_user_with_tz("user1")

        assert tz.value == "UTC"
        assert user_data.user_id == "user1"

    async def test_missing_user_returns_utc(self):
        with (
            patch(
                "app.workers.tasks.tracked_todo_tasks.load_user_context",
                new=AsyncMock(return_value=None),
            ),
            patch("app.workers.tasks.tracked_todo_tasks.log") as log,
        ):
            user_data, tz = await _load_user_with_tz("user1")

        assert user_data == AuthenticatedUser(user_id="user1")
        assert tz == Timezone.utc()
        # A user with no record is expected, not a failed load.
        log.warning.assert_not_called()

    async def test_exception_falls_back_to_utc(self):
        with patch(
            "app.workers.tasks.tracked_todo_tasks.load_user_context",
            new=AsyncMock(side_effect=RuntimeError("DB down")),
        ):
            user_data, tz = await _load_user_with_tz("user1")

        assert user_data == AuthenticatedUser(user_id="user1")
        assert tz == Timezone.utc()
