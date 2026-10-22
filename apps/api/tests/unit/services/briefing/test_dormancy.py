"""The idle ladder state the daily run reads off the user document."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.models.user_activity_models import UserActivityDates
from app.models.user_models import BriefingDormancy, UserDocument
from app.services.briefing import dormancy
from app.services.briefing.dormancy import DormancyState, state_from_user


class TestStateFromUser:
    def test_a_user_without_a_marker_is_awake_with_no_idle_days(self) -> None:
        assert state_from_user(UserDocument()) == DormancyState(
            idle_days=0, date=None, dormant_since=None
        )

    def test_the_marker_is_read_whole_and_mongos_naive_time_is_utc(self) -> None:
        user = UserDocument(
            briefing_dormancy=BriefingDormancy(
                idle_days=5, date="2026-10-13", dormant_since=datetime(2026, 10, 13, 8)
            )
        )

        assert state_from_user(user) == DormancyState(
            idle_days=5, date="2026-10-13", dormant_since=datetime(2026, 10, 13, 8, tzinfo=UTC)
        )

    def test_an_aware_dormant_since_keeps_its_offset(self) -> None:
        since = datetime.fromisoformat("2026-10-13T08:00:00+05:30")
        user = UserDocument(briefing_dormancy=BriefingDormancy(idle_days=5, dormant_since=since))

        state = state_from_user(user)

        assert state.dormant_since is not None
        assert state.dormant_since.utcoffset() == since.utcoffset()


_SINCE = datetime(2026, 10, 13, 8, tzinfo=UTC)


class TestLatestActivitySince:
    """Activity is the one last_active_at record, read fresh from Mongo."""

    @staticmethod
    def _dates(monkeypatch: pytest.MonkeyPatch, last_active_at: datetime | None) -> AsyncMock:
        read = AsyncMock(return_value=UserActivityDates(last_active_at=last_active_at))
        monkeypatch.setattr(dormancy.user_repository, "get_activity_dates", read)
        return read

    async def test_activity_after_the_cutoff_is_returned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        read = self._dates(monkeypatch, _SINCE + timedelta(hours=3))

        assert await dormancy.latest_activity_since("u1", _SINCE) == _SINCE + timedelta(hours=3)
        read.assert_awaited_once_with("u1")

    async def test_activity_before_the_cutoff_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._dates(monkeypatch, _SINCE - timedelta(seconds=1))

        assert await dormancy.latest_activity_since("u1", _SINCE) is None

    async def test_activity_at_the_cutoff_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._dates(monkeypatch, _SINCE)

        assert await dormancy.latest_activity_since("u1", _SINCE) == _SINCE

    async def test_a_naive_mongo_stamp_reads_as_utc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._dates(monkeypatch, datetime(2026, 10, 13, 11))

        assert await dormancy.latest_activity_since("u1", _SINCE) == datetime(
            2026, 10, 13, 11, tzinfo=UTC
        )

    async def test_a_user_never_seen_active_has_no_activity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: workflow runs write type=user messages, which used to count as the user."""
        self._dates(monkeypatch, None)

        assert await dormancy.latest_activity_since("u1", _SINCE) is None
