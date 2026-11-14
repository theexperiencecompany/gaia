"""The idle ladder state the daily run reads off the user document."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import time_machine

from app.constants.briefing import GOAL_QUESTION_REASK
from app.db.repositories.users import user_repository
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
        monkeypatch.setattr(user_repository, "get_activity_dates", read)
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


class TestClimbIdleLadder:
    async def test_an_idle_day_after_one_idle_day_reaches_the_warning_rung(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_day = AsyncMock()
        monkeypatch.setattr(user_repository, "set_dormancy_day", set_day)
        user = UserDocument(id="u1", created_at=datetime.now(UTC) - timedelta(days=90))
        prior = DormancyState(idle_days=1, date="2026-10-13", dormant_since=None)

        ladder = await dormancy.climb_idle_ladder(
            user, prior, "2026-10-14", has_news=False, has_goal=False
        )

        assert ladder == dormancy.IdleLadder(first_week=False, idle_days=2, wind_down="warn")
        set_day.assert_awaited_once_with("u1", idle_days=2, date_str="2026-10-14")


_NOW = datetime(2026, 11, 12, 2, 30, tzinfo=UTC)
_VETERAN = UserDocument(id="u1", created_at=_NOW - timedelta(days=300))


def _asked(days_ago: float, *, idle_days: int = 0) -> DormancyState:
    return DormancyState(
        idle_days=idle_days,
        date="2026-11-11",
        dormant_since=None,
        goal_asked_at=_NOW - timedelta(days=days_ago),
    )


class TestTheGoalQuestion:
    """A remembered goal is asked about once per GOAL_QUESTION_REASK, and an ignored one idles."""

    @pytest.fixture(autouse=True)
    def _frozen(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[AsyncMock]:
        set_day = AsyncMock()
        monkeypatch.setattr(user_repository, "set_dormancy_day", set_day)
        with time_machine.travel(_NOW, tick=False):
            yield set_day

    @staticmethod
    def _active_at(monkeypatch: pytest.MonkeyPatch, last_active_at: datetime | None) -> AsyncMock:
        read = AsyncMock(return_value=UserActivityDates(last_active_at=last_active_at))
        monkeypatch.setattr(user_repository, "get_activity_dates", read)
        return read

    async def test_a_goal_never_asked_about_is_asked_and_the_day_is_not_idle(self) -> None:
        prior = DormancyState(idle_days=0, date=None, dormant_since=None)

        ladder = await dormancy.climb_idle_ladder(
            _VETERAN, prior, "2026-11-12", has_news=False, has_goal=True
        )

        assert (ladder.goal_question, ladder.idle_days) == (dormancy.GoalQuestion.ASK, 0)

    async def test_a_goal_asked_inside_the_window_is_not_asked_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._active_at(monkeypatch, _NOW - timedelta(hours=1))

        ladder = await dormancy.climb_idle_ladder(
            _VETERAN,
            _asked(GOAL_QUESTION_REASK.days - 1),
            "2026-11-12",
            has_news=False,
            has_goal=True,
        )

        assert (ladder.goal_question, ladder.idle_days) == (dormancy.GoalQuestion.ASKED, 0)

    async def test_a_goal_asked_a_full_window_ago_is_asked_again(self) -> None:
        ladder = await dormancy.climb_idle_ladder(
            _VETERAN, _asked(GOAL_QUESTION_REASK.days), "2026-11-12", has_news=False, has_goal=True
        )

        assert ladder.goal_question is dormancy.GoalQuestion.ASK

    async def test_an_ignored_goal_question_lets_the_ladder_climb(
        self, monkeypatch: pytest.MonkeyPatch, _frozen: AsyncMock
    ) -> None:
        read = self._active_at(monkeypatch, _NOW - timedelta(days=3))

        ladder = await dormancy.climb_idle_ladder(
            _VETERAN, _asked(2, idle_days=1), "2026-11-12", has_news=False, has_goal=True
        )

        assert ladder == dormancy.IdleLadder(
            first_week=False,
            idle_days=2,
            wind_down="warn",
            goal_question=dormancy.GoalQuestion.ASKED,
        )
        _frozen.assert_awaited_once_with("u1", idle_days=2, date_str="2026-11-12")
        read.assert_awaited_once_with("u1")

    async def test_news_keeps_an_ignored_goal_day_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._active_at(monkeypatch, None)

        ladder = await dormancy.climb_idle_ladder(
            _VETERAN, _asked(2, idle_days=1), "2026-11-12", has_news=True, has_goal=True
        )

        assert (ladder.idle_days, ladder.wind_down) == (0, None)

    async def test_the_goal_question_is_recorded_only_when_it_goes_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        record = AsyncMock()
        monkeypatch.setattr(user_repository, "record_goal_question", record)
        asked = dormancy.IdleLadder(
            first_week=False, idle_days=0, wind_down=None, goal_question=dormancy.GoalQuestion.ASK
        )

        await dormancy.leave_idle_ladder(
            "u0", replace(asked, goal_question=dormancy.GoalQuestion.ASKED)
        )
        await dormancy.leave_idle_ladder("u1", asked)

        record.assert_awaited_once_with("u1")

    def test_the_marker_carries_when_the_goal_was_last_asked_about(self) -> None:
        user = UserDocument(
            briefing_dormancy=BriefingDormancy(goal_asked_at=datetime(2026, 11, 8, 2, 30))
        )

        assert state_from_user(user).goal_asked_at == datetime(2026, 11, 8, 2, 30, tzinfo=UTC)
