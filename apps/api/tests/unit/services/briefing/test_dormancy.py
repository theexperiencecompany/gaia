"""The idle ladder state the daily run reads off the user document."""

from datetime import UTC, datetime

from app.models.user_models import BriefingDormancy, UserDocument
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
