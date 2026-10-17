"""The idle ladder state the daily run reads off the user document."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

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
    """Last activity comes off the loaded user plus one conversation read — no user re-read."""

    async def test_the_newer_of_the_web_stamp_and_the_last_message_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        messages = AsyncMock(return_value=_SINCE + timedelta(hours=3))
        monkeypatch.setattr(dormancy.conversation_repository, "latest_user_message_since", messages)
        user = UserDocument(id="u1", last_active_at=datetime(2026, 10, 13, 9))  # naive = UTC

        assert await dormancy.latest_activity_since(user, _SINCE) == _SINCE + timedelta(hours=3)
        messages.assert_awaited_once_with("u1", _SINCE)

    async def test_a_web_stamp_before_the_cutoff_is_no_activity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            dormancy.conversation_repository,
            "latest_user_message_since",
            AsyncMock(return_value=None),
        )
        user = UserDocument(id="u1", last_active_at=_SINCE - timedelta(seconds=1))

        assert await dormancy.latest_activity_since(user, _SINCE) is None

    async def test_a_web_stamp_at_the_cutoff_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            dormancy.conversation_repository,
            "latest_user_message_since",
            AsyncMock(return_value=None),
        )

        user = UserDocument(id="u1", last_active_at=_SINCE)

        assert await dormancy.latest_activity_since(user, _SINCE) == _SINCE

    async def test_a_newer_naive_web_stamp_wins_and_reads_as_utc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            dormancy.conversation_repository,
            "latest_user_message_since",
            AsyncMock(return_value=_SINCE + timedelta(hours=1)),
        )
        user = UserDocument(id="u1", last_active_at=datetime(2026, 10, 13, 11))  # naive = UTC

        assert await dormancy.latest_activity_since(user, _SINCE) == datetime(
            2026, 10, 13, 11, tzinfo=UTC
        )

    async def test_a_user_never_seen_on_the_web_is_active_by_their_last_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            dormancy.conversation_repository,
            "latest_user_message_since",
            AsyncMock(return_value=_SINCE + timedelta(hours=1)),
        )

        user = UserDocument(id="u1", last_active_at=None)

        assert await dormancy.latest_activity_since(user, _SINCE) == _SINCE + timedelta(hours=1)
