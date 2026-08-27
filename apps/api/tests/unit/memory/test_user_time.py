"""Journal-day bucketing on the user's wall clock (``app.memory.user_time``)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.memory import user_time

USER = "user-1"


@contextmanager
def _patch_user(timezone: str | None, *, missing: bool = False) -> Iterator[AsyncMock]:
    value = None if missing else SimpleNamespace(timezone=timezone)
    mock_get = AsyncMock(return_value=value)
    with patch.object(user_time.user_repository, "get", mock_get):
        yield mock_get


@pytest.mark.unit
class TestResolveUserTimezone:
    async def test_stored_iana_zone_is_resolved(self) -> None:
        with _patch_user("Asia/Kolkata") as mock_get:
            tz = await user_time.resolve_user_timezone(USER)
        mock_get.assert_awaited_once_with(USER)
        assert tz.value == "Asia/Kolkata"
        assert tz.tzinfo == ZoneInfo("Asia/Kolkata")

    async def test_missing_user_falls_back_to_utc(self) -> None:
        with _patch_user(None, missing=True):
            tz = await user_time.resolve_user_timezone(USER)
        assert tz.is_utc

    async def test_unset_timezone_falls_back_to_utc(self) -> None:
        with _patch_user(None):
            tz = await user_time.resolve_user_timezone(USER)
        assert tz.is_utc

    async def test_invalid_timezone_falls_back_to_utc_without_raising(self) -> None:
        with _patch_user("Not/AZone"):
            tz = await user_time.resolve_user_timezone(USER)
        assert tz.is_utc


@pytest.mark.unit
class TestLocalToday:
    async def test_late_utc_evening_is_the_next_day_in_kolkata(self) -> None:
        fixed = datetime(2026, 8, 26, 21, 30, tzinfo=UTC)
        with _patch_user("Asia/Kolkata") as mock_get, patch.object(user_time, "datetime") as clock:
            clock.now.return_value = fixed
            assert await user_time.local_today(USER) == date(2026, 8, 27)
        clock.now.assert_called_once_with(UTC)
        mock_get.assert_awaited_once_with(USER)

    async def test_early_utc_morning_is_the_previous_day_in_los_angeles(self) -> None:
        fixed = datetime(2026, 8, 27, 3, 0, tzinfo=UTC)
        with (
            _patch_user("America/Los_Angeles"),
            patch.object(user_time, "datetime") as clock,
        ):
            clock.now.return_value = fixed
            assert await user_time.local_today(USER) == date(2026, 8, 26)
        clock.now.assert_called_once_with(UTC)

    async def test_utc_fallback_keeps_the_utc_day(self) -> None:
        fixed = datetime(2026, 8, 26, 21, 30, tzinfo=UTC)
        with (
            _patch_user(None, missing=True),
            patch.object(user_time, "datetime") as clock,
        ):
            clock.now.return_value = fixed
            assert await user_time.local_today(USER) == date(2026, 8, 26)


@pytest.mark.unit
class TestRepositoryFailureFallsBackToUTC:
    async def test_a_repository_error_resolves_to_utc_instead_of_raising(self) -> None:
        """The repository raises for a malformed user id (bson InvalidId) and
        for infra failures; timezone resolution is enrichment, so a lookup
        failure must degrade to UTC — raising here crashed every retain in the
        real-infra suite, whose synthetic user ids are not ObjectIds."""
        with patch.object(
            user_time.user_repository, "get", AsyncMock(side_effect=ValueError("bad id"))
        ):
            tz = await user_time.resolve_user_timezone("test-mem-notanobjectid")

        assert tz == user_time.Timezone.utc()

    async def test_the_degraded_lookup_is_visible_in_the_wide_event(self) -> None:
        """Failing open must not fail silent: the fallback warns with the
        event name and the structured fields (user, error type, message) that
        make a broken timezone preference diagnosable from the wide event."""
        with (
            patch.object(
                user_time.user_repository, "get", AsyncMock(side_effect=ValueError("bad id"))
            ),
            patch.object(user_time, "log") as mock_log,
        ):
            await user_time.resolve_user_timezone("test-mem-notanobjectid")

        mock_log.warning.assert_called_once_with(
            "memory_user_timezone_lookup_failed",
            user_id="test-mem-notanobjectid",
            error_type="ValueError",
            error="bad id",
        )
