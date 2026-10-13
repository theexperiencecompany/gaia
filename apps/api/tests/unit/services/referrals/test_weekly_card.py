"""When chat surfaces the Monday recap card: the user's own Monday, for a week with work in it."""

from datetime import UTC, datetime

import pytest

from app.models.user_models import UserDocument
from app.schemas.usage import TimeSavedSummary
from app.services.referrals.weekly_card import weekly_card_due

# Sunday 20:00 UTC is already Monday in Kolkata (+05:30) and still Sunday in New York.
SUNDAY_EVENING_UTC = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
MONDAY_NOON_UTC = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _stats(minutes_saved: int) -> TimeSavedSummary:
    return TimeSavedSummary(
        window_start=datetime(2026, 10, 12, tzinfo=UTC),
        window_end=datetime(2026, 10, 19, tzinfo=UTC),
        actions=minutes_saved,
        workflow_runs=0,
        minutes_saved=minutes_saved,
    )


@pytest.mark.parametrize(
    ("timezone", "now", "due"),
    [
        ("Asia/Kolkata", SUNDAY_EVENING_UTC, True),
        ("America/New_York", SUNDAY_EVENING_UTC, False),
        (None, MONDAY_NOON_UTC, True),
        (None, SUNDAY_EVENING_UTC, False),
    ],
)
def test_the_card_is_due_on_the_users_local_monday(
    timezone: str | None, now: datetime, due: bool
) -> None:
    user = UserDocument(name="Aryan", email="a@example.com", timezone=timezone)
    assert weekly_card_due(user, _stats(30), now) is due


def test_a_week_with_nothing_saved_never_shows_the_card() -> None:
    user = UserDocument(name="Aryan", email="a@example.com")
    assert weekly_card_due(user, _stats(0), MONDAY_NOON_UTC) is False
