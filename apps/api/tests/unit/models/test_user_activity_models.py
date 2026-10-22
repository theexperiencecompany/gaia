"""The activity scale: where each status starts and ends, and what a never-seen user reads as."""

from datetime import UTC, datetime, timedelta

import pytest

from app.constants.user_activity import DORMANT_AFTER, IDLE_AFTER, ActivityStatus
from app.models.user_activity_models import UserActivityDates, status_window

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
TICK = timedelta(seconds=1)


@pytest.mark.parametrize(
    ("unseen_for", "expected"),
    [
        (timedelta(0), ActivityStatus.ACTIVE),
        (IDLE_AFTER - TICK, ActivityStatus.ACTIVE),
        (IDLE_AFTER, ActivityStatus.IDLE),
        (DORMANT_AFTER - TICK, ActivityStatus.IDLE),
        (DORMANT_AFTER, ActivityStatus.DORMANT),
        (timedelta(days=400), ActivityStatus.DORMANT),
    ],
)
def test_the_status_follows_time_since_last_seen(unseen_for: timedelta, expected: ActivityStatus):
    assert UserActivityDates(last_active_at=NOW - unseen_for).status(NOW) is expected


def test_a_never_seen_user_is_judged_from_signup():
    signed_up = NOW - IDLE_AFTER - TICK
    assert UserActivityDates(created_at=signed_up).status(NOW) is ActivityStatus.IDLE


def test_activity_wins_over_an_old_signup():
    dates = UserActivityDates(created_at=NOW - timedelta(days=400), last_active_at=NOW)
    assert dates.status(NOW) is ActivityStatus.ACTIVE


def test_a_naive_mongo_datetime_is_read_as_utc():
    naive = (NOW - IDLE_AFTER - TICK).replace(tzinfo=None)
    assert UserActivityDates(last_active_at=naive).status(NOW) is ActivityStatus.IDLE


def test_a_user_with_no_dates_at_all_is_dormant():
    assert UserActivityDates().status(NOW) is ActivityStatus.DORMANT


@pytest.mark.parametrize(
    "unseen_for", [timedelta(0), IDLE_AFTER, DORMANT_AFTER, timedelta(days=90)]
)
def test_the_query_window_and_the_python_status_agree(unseen_for: timedelta):
    """The repository queries status_window; it must put a user exactly where status() does."""
    last_seen = NOW - unseen_for
    status = UserActivityDates(last_active_at=last_seen).status(NOW)
    after, until = status_window(status, NOW)
    assert after is None or last_seen > after
    assert until is None or last_seen <= until
