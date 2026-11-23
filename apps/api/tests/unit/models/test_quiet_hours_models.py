"""Quiet hours on the user's own clock: 22:00 to 08:00 unless they set their own; a held run waits for their end."""

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import pytest

from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS, QuietHours

pytestmark = pytest.mark.unit

KOLKATA = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")
DEFAULT = DEFAULT_QUIET_HOURS
DAYTIME = QuietHours(enabled=True, start_hour=13, end_hour=15)
LATE = QuietHours(enabled=True, start_hour=1, end_hour=9)


def _at(hour: int, minute: int = 0, day: int = 3) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=KOLKATA)


@pytest.mark.parametrize(
    ("hours", "hour", "minute", "quiet"),
    [
        (DEFAULT, 21, 59, False),
        (DEFAULT, 22, 0, True),
        (DEFAULT, 0, 30, True),
        (DEFAULT, 7, 59, True),
        (DEFAULT, 8, 0, False),
        (DAYTIME, 12, 59, False),
        (DAYTIME, 13, 0, True),
        (DAYTIME, 14, 59, True),
        (DAYTIME, 15, 0, False),
        (LATE, 23, 0, False),
        (LATE, 1, 0, True),
        (LATE, 8, 59, True),
    ],
)
def test_quiet_hours_cover_their_own_span(
    hours: QuietHours, hour: int, minute: int, quiet: bool
) -> None:
    assert hours.contains(_at(hour, minute)) is quiet


def test_quiet_hours_that_are_off_cover_no_hour() -> None:
    off = DEFAULT_QUIET_HOURS.model_copy(update={"enabled": False})

    assert not any(off.contains(_at(hour)) for hour in range(24))


@pytest.mark.parametrize(
    ("hours", "moment", "expected"),
    [
        (DEFAULT, _at(22), _at(8, day=4)),
        (DEFAULT, _at(23, 40), _at(8, day=4)),
        (DEFAULT, _at(2, 15, day=4), _at(8, day=4)),
        (DAYTIME, _at(14, 10), _at(15)),
        (LATE, _at(3), _at(9)),
        # The night the US leaves daylight time: 08:00 is EST, nine wall hours and ten real ones on.
        (
            DEFAULT,
            datetime(2026, 10, 31, 23, 0, tzinfo=NEW_YORK),
            datetime(2026, 11, 1, 8, 0, tzinfo=NEW_YORK),
        ),
    ],
    ids=["at-start", "before-midnight", "after-midnight", "daytime", "late", "across-a-dst-change"],
)
def test_a_moment_in_quiet_hours_waits_for_their_end(
    hours: QuietHours, moment: datetime, expected: datetime
) -> None:
    assert hours.end_after(moment) == expected


def test_a_moment_outside_quiet_hours_is_its_own_answer() -> None:
    assert DEFAULT.end_after(_at(14, 5)) == _at(14, 5)


def test_quiet_hours_that_start_when_they_end_are_refused() -> None:
    with pytest.raises(ValidationError) as refused:
        QuietHours(enabled=True, start_hour=8, end_hour=8)

    assert [e["msg"] for e in refused.value.errors()] == [
        "Value error, quiet hours must start and end at different hours"
    ]


@pytest.mark.parametrize("hour", [-1, 24])
def test_an_hour_off_the_clock_is_refused(hour: int) -> None:
    with pytest.raises(ValidationError):
        QuietHours(enabled=True, start_hour=hour, end_hour=8)
