"""Quiet hours are 22:00 to 08:00 on the user's own clock; a held run waits for their end."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.utils.quiet_hours import after_quiet_hours, in_quiet_hours

pytestmark = pytest.mark.unit

KOLKATA = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    ("hour", "minute", "quiet"),
    [(21, 59, False), (22, 0, True), (23, 8, True), (0, 30, True), (7, 59, True), (8, 0, False)],
)
def test_quiet_hours_span_midnight(hour: int, minute: int, quiet: bool) -> None:
    assert in_quiet_hours(datetime(2026, 10, 3, hour, minute, tzinfo=KOLKATA)) is quiet


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (
            datetime(2026, 10, 3, 23, 40, tzinfo=KOLKATA),
            datetime(2026, 10, 4, 8, 0, tzinfo=KOLKATA),
        ),
        (
            datetime(2026, 10, 4, 2, 15, tzinfo=KOLKATA),
            datetime(2026, 10, 4, 8, 0, tzinfo=KOLKATA),
        ),
        # The night the US leaves daylight time: 08:00 is EST, nine wall hours and ten real ones on.
        (
            datetime(2026, 10, 31, 23, 0, tzinfo=NEW_YORK),
            datetime(2026, 11, 1, 8, 0, tzinfo=NEW_YORK),
        ),
    ],
    ids=["before-midnight", "after-midnight", "across-a-dst-change"],
)
def test_a_moment_in_quiet_hours_waits_for_their_end(moment: datetime, expected: datetime) -> None:
    assert after_quiet_hours(moment) == expected


def test_a_moment_outside_quiet_hours_is_its_own_answer() -> None:
    moment = datetime(2026, 10, 3, 14, 5, tzinfo=KOLKATA)

    assert after_quiet_hours(moment) == moment
