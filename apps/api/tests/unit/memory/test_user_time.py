"""Journal-day bucketing on the user's wall clock (app.memory.user_time)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.repositories.users import user_repository
from app.memory import user_time
from app.utils import clock

USER = "507f1f77bcf86cd799439011"


@contextmanager
def _patch_user(timezone: str | None, *, missing: bool = False) -> Iterator[AsyncMock]:
    value = None if missing else SimpleNamespace(timezone=timezone)
    mock_get = AsyncMock(return_value=value)
    with patch.object(user_repository, "get", mock_get):
        yield mock_get


@contextmanager
def _utc_now(instant: datetime) -> Iterator[None]:
    with patch.object(clock, "now", return_value=instant):
        yield


@pytest.mark.unit
class TestLocalToday:
    async def test_late_utc_evening_is_the_next_day_in_kolkata(self) -> None:
        with (
            _patch_user("Asia/Kolkata") as mock_get,
            _utc_now(datetime(2026, 8, 26, 21, 30, tzinfo=UTC)),
        ):
            assert await user_time.local_today(USER) == date(2026, 8, 27)
        mock_get.assert_awaited_once_with(USER)

    async def test_early_utc_morning_is_the_previous_day_in_los_angeles(self) -> None:
        with (
            _patch_user("America/Los_Angeles"),
            _utc_now(datetime(2026, 8, 27, 3, 0, tzinfo=UTC)),
        ):
            assert await user_time.local_today(USER) == date(2026, 8, 26)

    async def test_utc_fallback_keeps_the_utc_day(self) -> None:
        with (
            _patch_user(None, missing=True),
            _utc_now(datetime(2026, 8, 26, 21, 30, tzinfo=UTC)),
        ):
            assert await user_time.local_today(USER) == date(2026, 8, 26)

    async def test_a_synthetic_user_id_keeps_the_utc_day_without_a_profile_read(self) -> None:
        """Memory's real-infra suite files journal days under ids that are not ObjectIds."""
        with (
            _patch_user("Asia/Kolkata") as mock_get,
            _utc_now(datetime(2026, 8, 26, 21, 30, tzinfo=UTC)),
        ):
            assert await user_time.local_today("test-mem-notanobjectid") == date(2026, 8, 26)
        mock_get.assert_not_awaited()
