"""Unit tests for the timezone FastAPI dependencies.

The pure precedence rule (resolve_home_timezone) is covered in test_timezone.py.
Here we test the dependency wrappers — specifically the heal SIDE EFFECT: a
stored "UTC" being corrected (backfilled) from a valid browser header, which is
the root-cause fix for workflows/reminders running in UTC.
"""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.dependencies.oauth_dependencies import (
    get_user_timezone,
    get_user_timezone_from_preferences,
)

_BACKFILL = "app.api.v1.dependencies.oauth_dependencies._backfill_user_timezone"


@pytest.mark.unit
class TestGetUserTimezoneFromPreferences:
    async def test_real_stored_zone_returned_without_backfill(self) -> None:
        with patch(_BACKFILL, new_callable=AsyncMock) as backfill:
            result = await get_user_timezone_from_preferences(
                user={"user_id": "u1", "timezone": "America/New_York"},
                x_timezone="Asia/Kolkata",
            )
            await asyncio.sleep(0)  # let any fire-and-forget task run
        assert result == "America/New_York"
        backfill.assert_not_awaited()

    async def test_stored_utc_is_healed_and_backfilled_from_header(self) -> None:
        with patch(_BACKFILL, new_callable=AsyncMock) as backfill:
            result = await get_user_timezone_from_preferences(
                user={"user_id": "u1", "timezone": "UTC"},
                x_timezone="Asia/Kolkata",
            )
            await asyncio.sleep(0)
        assert result == "Asia/Kolkata"
        backfill.assert_awaited_once_with("u1", "Asia/Kolkata")

    async def test_empty_stored_is_filled_and_backfilled(self) -> None:
        with patch(_BACKFILL, new_callable=AsyncMock) as backfill:
            result = await get_user_timezone_from_preferences(
                user={"user_id": "u1"},
                x_timezone="Asia/Kolkata",
            )
            await asyncio.sleep(0)
        assert result == "Asia/Kolkata"
        backfill.assert_awaited_once_with("u1", "Asia/Kolkata")

    async def test_genuine_utc_is_not_healed(self) -> None:
        with patch(_BACKFILL, new_callable=AsyncMock) as backfill:
            result = await get_user_timezone_from_preferences(
                user={"user_id": "u1", "timezone": "UTC"},
                x_timezone="UTC",
            )
            await asyncio.sleep(0)
        assert result == "UTC"
        backfill.assert_not_awaited()

    async def test_no_signal_falls_back_to_utc_without_backfill(self) -> None:
        with patch(_BACKFILL, new_callable=AsyncMock) as backfill:
            result = await get_user_timezone_from_preferences(
                user={"user_id": "u1"},
                x_timezone="",
            )
            await asyncio.sleep(0)
        assert result == "UTC"
        backfill.assert_not_awaited()

    async def test_garbage_header_does_not_heal(self) -> None:
        with patch(_BACKFILL, new_callable=AsyncMock) as backfill:
            result = await get_user_timezone_from_preferences(
                user={"user_id": "u1", "timezone": "UTC"},
                x_timezone="Not/A_Zone",
            )
            await asyncio.sleep(0)
        assert result == "UTC"
        backfill.assert_not_awaited()


@pytest.mark.unit
class TestGetUserTimezoneHeaderDependency:
    def test_returns_canonical_zone_and_now_in_zone(self) -> None:
        tz_str, now = get_user_timezone(x_timezone="Asia/Kolkata")
        assert tz_str == "Asia/Kolkata"
        assert now.utcoffset() == timedelta(hours=5, minutes=30)

    def test_bad_header_falls_back_to_utc_without_raising(self) -> None:
        # The old ZoneInfo(header) raised on garbage; Timezone.parse must not.
        tz_str, now = get_user_timezone(x_timezone="Not/A_Zone")
        assert tz_str == "UTC"
        assert now.utcoffset() == timedelta(0)

    def test_offset_header_is_accepted(self) -> None:
        # ZoneInfo("+05:30") would have raised; the value object handles offsets.
        tz_str, now = get_user_timezone(x_timezone="+05:30")
        assert tz_str == "+05:30"
        assert now.utcoffset() == timedelta(hours=5, minutes=30)
