"""Cross-cutting timezone matrix: cron scheduling, ``Timezone.parse``,
waking-hour windows, and briefing-clock date derivation, all exercised
against real-world IANA zones (half-hour/45-minute offsets, +14/-11 extremes,
and DST transitions including the unusual 30-minute Lord Howe shift).

Every expected UTC instant below is derived independently from the zone's
UTC offset at that date (looked up via ``zoneinfo``/public DST-transition
dates, not by calling the function under test) and written out by hand in
each test's comment.

``freeze_time`` is wrapped with ``ignore=["transformers"]`` because
freezegun's teardown walks every loaded module and touches attributes on
huggingface's lazily-loaded ``transformers`` submodules (pulled in
transitively via ``app.memory.engine``), which triggers a real import of a
torch-only submodule and raises ``NameError: name 'torch' is not defined``.
The same workaround already exists in
``tests/integration/test_worker_task_lifecycle.py``.
"""

from datetime import UTC, datetime

from freezegun import freeze_time as _freeze_time
import pytest

from app.constants.todos import is_waking_hour
from app.services.briefing.context import day_start_utc, resolve_clock
from app.utils.cron_utils import get_next_run_time
from app.utils.timezone import Timezone

_FREEZEGUN_IGNORE = ["transformers"]


def freeze_time(*args, **kwargs):
    """Wrapper that always passes ignore=["transformers"] (see module docstring)."""
    kwargs.setdefault("ignore", _FREEZEGUN_IGNORE)
    return _freeze_time(*args, **kwargs)


DAILY_8AM = "0 8 * * *"


# ---------------------------------------------------------------------------
# get_next_run_time — cron "0 8 * * *" across real-world zones and DST
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCronMatrixNonDstZones:
    def test_kolkata_plus_0530(self) -> None:
        # Frozen 2026-06-15T00:00Z = 05:30 IST (before 8am local same day).
        # Next 8am IST = 08:00 - 5:30 = 02:30 UTC same day.
        base = datetime(2026, 6, 15, 0, 0, tzinfo=UTC)
        result = get_next_run_time(DAILY_8AM, base_time=base, tz=Timezone.parse("Asia/Kolkata"))
        assert result == datetime(2026, 6, 15, 2, 30, tzinfo=UTC)

    def test_kathmandu_plus_0545(self) -> None:
        # Frozen 2026-06-15T00:00Z = 05:45 local (+5:45, no DST).
        # Next 8am local = 08:00 - 5:45 = 02:15 UTC same day.
        base = datetime(2026, 6, 15, 0, 0, tzinfo=UTC)
        result = get_next_run_time(DAILY_8AM, base_time=base, tz=Timezone.parse("Asia/Kathmandu"))
        assert result == datetime(2026, 6, 15, 2, 15, tzinfo=UTC)

    def test_kiritimati_plus_14(self) -> None:
        # Frozen 2026-06-15T10:00Z = 2026-06-16 00:00 local (+14, no DST).
        # Next 8am local is the same local day: 08:00 - 14:00 = 2026-06-15T18:00Z.
        base = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
        result = get_next_run_time(
            DAILY_8AM, base_time=base, tz=Timezone.parse("Pacific/Kiritimati")
        )
        assert result == datetime(2026, 6, 15, 18, 0, tzinfo=UTC)

    def test_niue_minus_11(self) -> None:
        # Frozen 2026-06-15T00:00Z = 2026-06-14 13:00 local (-11, no DST;
        # already past 8am local on June 14). Next fire is June 15 08:00 local
        # = 08:00 + 11:00 = 2026-06-15T19:00Z.
        base = datetime(2026, 6, 15, 0, 0, tzinfo=UTC)
        result = get_next_run_time(DAILY_8AM, base_time=base, tz=Timezone.parse("Pacific/Niue"))
        assert result == datetime(2026, 6, 15, 19, 0, tzinfo=UTC)


@pytest.mark.unit
class TestCronMatrixLordHoweHalfHourDst:
    """Australia/Lord_Howe is the one IANA zone with a 30-minute DST shift
    (+10:30 standard <-> +11:00 daylight), not the usual full hour. 2026
    transitions (looked up via zoneinfo, not the function under test):
    fall back (DST->STD) at 2026-04-04T15:00:00Z; spring forward (STD->DST)
    at 2026-10-03T15:30:00Z.
    """

    def test_before_october_spring_forward_is_standard_offset(self) -> None:
        # Frozen 2026-10-02T20:00Z = 2026-10-03 06:30 local (+10:30, before
        # the Oct 3->4 transition). Next 8am local = 08:00 - 10:30 = 2026-10-02T21:30Z.
        base = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
        result = get_next_run_time(
            DAILY_8AM, base_time=base, tz=Timezone.parse("Australia/Lord_Howe")
        )
        assert result == datetime(2026, 10, 2, 21, 30, tzinfo=UTC)

    def test_after_october_spring_forward_is_daylight_offset(self) -> None:
        # Frozen 2026-10-03T18:00Z = 2026-10-04 05:00 local (+11:00, after the
        # transition). Next 8am local = 08:00 - 11:00 = 2026-10-03T21:00Z.
        base = datetime(2026, 10, 3, 18, 0, tzinfo=UTC)
        result = get_next_run_time(
            DAILY_8AM, base_time=base, tz=Timezone.parse("Australia/Lord_Howe")
        )
        assert result == datetime(2026, 10, 3, 21, 0, tzinfo=UTC)

    def test_before_april_fall_back_is_daylight_offset(self) -> None:
        # Frozen 2026-04-03T20:00Z = 2026-04-04 07:00 local (+11:00, before
        # the Apr 4->5 fall-back). Next 8am local = 08:00 - 11:00 = 2026-04-03T21:00Z.
        base = datetime(2026, 4, 3, 20, 0, tzinfo=UTC)
        result = get_next_run_time(
            DAILY_8AM, base_time=base, tz=Timezone.parse("Australia/Lord_Howe")
        )
        assert result == datetime(2026, 4, 3, 21, 0, tzinfo=UTC)

    def test_after_april_fall_back_is_standard_offset(self) -> None:
        # Frozen 2026-04-05T20:00Z = 2026-04-06 06:30 local (+10:30, after the
        # fall-back). Next 8am local = 08:00 - 10:30 = 2026-04-05T21:30Z.
        base = datetime(2026, 4, 5, 20, 0, tzinfo=UTC)
        result = get_next_run_time(
            DAILY_8AM, base_time=base, tz=Timezone.parse("Australia/Lord_Howe")
        )
        assert result == datetime(2026, 4, 5, 21, 30, tzinfo=UTC)


@pytest.mark.unit
class TestCronMatrixNewYorkDst:
    def test_spring_forward_2026_03_08_fires_at_edt_offset(self) -> None:
        # Frozen local 2026-03-08T00:00 EST (-5) = 2026-03-08T05:00Z. The next
        # 8am fire (2026-03-08 08:00 local) is AFTER that night's 2am->3am
        # spring-forward gap, so it resolves at EDT (-4).
        # Fails if cron is evaluated in a fixed offset instead of the real
        # IANA zone: expected UTC hour differs by 1 depending on which side
        # of the gap "08:00" is resolved on.
        base = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
        result = get_next_run_time(DAILY_8AM, base_time=base, tz=Timezone.parse("America/New_York"))
        assert result == datetime(2026, 3, 8, 12, 0, tzinfo=UTC)

    def test_fall_back_2026_11_01_fires_at_est_offset(self) -> None:
        # Frozen local 2026-11-01T00:00 EDT (-4) = 2026-11-01T04:00Z. The next
        # 8am fire is after that night's 2am->1am fall-back, so it resolves
        # at EST (-5): 08:00 + 5:00 = 2026-11-01T13:00Z.
        base = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
        result = get_next_run_time(DAILY_8AM, base_time=base, tz=Timezone.parse("America/New_York"))
        assert result == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)

    def test_dst_gap_2_30am_does_not_exist_pinned_behavior(self) -> None:
        """Cron "30 2 * * *" frozen at 2026-03-08 01:00 EST — the naive next
        occurrence is 02:30 local, which never happens that night (the clock
        jumps 02:00 -> 03:00). This does not have an independently "correct"
        expected value; it pins the library's ACTUAL behavior so a change in
        that behavior is caught rather than silently drifting.

        Observed behavior (verified by running the real code): croniter
        advances the NAIVE wall clock to 02:30, and attaching the zone's
        tzinfo to that nonexistent local time resolves it via the pre-gap
        (EST, -5) offset — i.e. UTC = 02:30 + 5:00 = 07:30Z. Converted back,
        07:30Z falls after the 07:00Z transition instant, so it displays as
        03:30 EDT: the fire effectively slides forward by the 1-hour gap
        instead of landing on the nonexistent wall-clock time.
        """
        base = datetime(2026, 3, 8, 6, 0, tzinfo=UTC)  # local 01:00 EST
        result = get_next_run_time(
            "30 2 * * *", base_time=base, tz=Timezone.parse("America/New_York")
        )
        assert result == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
        local = Timezone.parse("America/New_York").localize(result)
        assert (local.hour, local.minute) == (3, 30)
        assert local.utcoffset() is not None and local.utcoffset().total_seconds() == -4 * 3600


@pytest.mark.unit
class TestCronMatrixLondonDst:
    def test_2026_03_29_transition_fires_at_bst_offset(self) -> None:
        # Frozen 2026-03-29T00:00Z = 00:00 GMT (before that day's 01:00->02:00
        # spring-forward). Next 8am local falls after the transition, so it
        # resolves at BST (+1): 08:00 - 1:00 = 2026-03-29T07:00Z.
        base = datetime(2026, 3, 29, 0, 0, tzinfo=UTC)
        result = get_next_run_time(DAILY_8AM, base_time=base, tz=Timezone.parse("Europe/London"))
        assert result == datetime(2026, 3, 29, 7, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Timezone.parse — contract per its own docstring: IANA name, ``+HH:MM``
# offset, garbage, None.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimezoneParseContract:
    def test_iana_name_resolves_to_its_own_zoneinfo(self) -> None:
        tz = Timezone.parse("Pacific/Kiritimati")
        assert tz.value == "Pacific/Kiritimati"
        # Kiritimati has no DST, so any reference instant gives the same +14:00.
        offset = tz.tzinfo.utcoffset(datetime(2026, 6, 15, tzinfo=UTC))
        assert offset is not None and offset.total_seconds() == 14 * 3600

    def test_raw_offset_string_resolves_to_fixed_offset(self) -> None:
        tz = Timezone.parse("+05:30")
        assert tz.value == "+05:30"
        assert tz.tzinfo.utcoffset(None).total_seconds() == 5.5 * 3600

    def test_garbage_falls_back_to_utc_never_raises(self) -> None:
        # The docstring's explicit contract: unrecognized input falls back to
        # UTC with a warning rather than raising.
        tz = Timezone.parse("not-a-real-zone/nonsense")
        assert tz.is_utc

    def test_none_falls_back_to_utc(self) -> None:
        assert Timezone.parse(None).is_utc


# ---------------------------------------------------------------------------
# is_waking_hour — hour-granularity boundary in a non-UTC zone (Asia/Kolkata,
# +5:30). The function reads only ``.hour``, so the boundary is exactly on
# the hour regardless of minute.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsWakingHourBoundaries:
    def test_08_59_ist_is_not_yet_waking(self) -> None:
        # 2026-06-15T03:29Z = 08:59 IST (hour=8, before WAKING_HOUR_START=9).
        # Fails if the start boundary check used "<=" instead of the correct
        # "<" against WAKING_HOUR_START, or ignored the user's own zone.
        with freeze_time(datetime(2026, 6, 15, 3, 29, tzinfo=UTC)):
            assert is_waking_hour("Asia/Kolkata") is False

    def test_09_00_ist_is_waking(self) -> None:
        # 2026-06-15T03:30Z = 09:00 IST (hour=9, the start boundary itself).
        with freeze_time(datetime(2026, 6, 15, 3, 30, tzinfo=UTC)):
            assert is_waking_hour("Asia/Kolkata") is True

    def test_21_59_ist_is_still_waking(self) -> None:
        # 2026-06-15T16:29Z = 21:59 IST (hour=21, still under WAKING_HOUR_END=22).
        with freeze_time(datetime(2026, 6, 15, 16, 29, tzinfo=UTC)):
            assert is_waking_hour("Asia/Kolkata") is True

    def test_22_00_ist_is_no_longer_waking(self) -> None:
        # 2026-06-15T16:30Z = 22:00 IST (hour=22, the end boundary itself —
        # the window is a half-open [9, 22) interval).
        # Fails if the end boundary check used "<=" instead of "<".
        with freeze_time(datetime(2026, 6, 15, 16, 30, tzinfo=UTC)):
            assert is_waking_hour("Asia/Kolkata") is False


# ---------------------------------------------------------------------------
# Briefing clock (resolve_clock / day_start_utc) — same frozen UTC instant,
# two zones 25 hours apart (+14 vs -11) land on different local dates.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBriefingClockAcrossExtremeZones:
    FROZEN = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    def test_kiritimati_and_niue_land_on_different_local_dates(self) -> None:
        # 2026-06-15T12:00Z + 14:00 = 2026-06-16 02:00 local (Kiritimati).
        # 2026-06-15T12:00Z - 11:00 = 2026-06-15 01:00 local (Niue).
        with freeze_time(self.FROZEN):
            kiri = resolve_clock("Pacific/Kiritimati")
            niue = resolve_clock("Pacific/Niue")

        assert kiri.date_str == "2026-06-16"
        assert niue.date_str == "2026-06-15"
        assert kiri.date_str != niue.date_str

        # date(2026, 6, 16) is a Tuesday, date(2026, 6, 15) is a Monday
        # (independently confirmed via Python's own date.weekday()).
        assert kiri.now_local.date().weekday() == 1  # Tuesday
        assert niue.now_local.date().weekday() == 0  # Monday

        # day_of_year: 2026 is not a leap year, so day-of-year is a plain
        # cumulative count. June 16 is the 167th day, June 15 the 166th.
        assert kiri.day_of_year == 167
        assert niue.day_of_year == 166

    def test_day_start_utc_uses_local_midnight_not_utc_midnight(self) -> None:
        # Kiritimati local midnight on its "today" (2026-06-16) is
        # 2026-06-16T00:00+14:00 = 2026-06-15T10:00Z.
        # Fails if day_start_utc used UTC midnight instead of the user's own
        # local midnight (would give 2026-06-16T00:00Z instead).
        with freeze_time(self.FROZEN):
            kiri = resolve_clock("Pacific/Kiritimati")
            assert day_start_utc(kiri, 0) == datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
            # One day back: local midnight 2026-06-15+14:00 = 2026-06-14T10:00Z.
            assert day_start_utc(kiri, 1) == datetime(2026, 6, 14, 10, 0, tzinfo=UTC)

    def test_day_start_is_expressed_in_utc_not_the_machine_local_zone(self) -> None:
        # `is UTC`, not `== UTC`: converting to the machine's own zone instead
        # of UTC yields the same instant, and on a UTC-configured CI runner it
        # also compares equal. Only identity separates "converted to UTC" from
        # "converted to wherever this box happens to be".
        with freeze_time(self.FROZEN):
            kiri = resolve_clock("Pacific/Kiritimati")
            assert day_start_utc(kiri, 0).tzinfo is UTC

    def test_a_user_with_no_timezone_gets_a_utc_clock(self) -> None:
        # Most users never set one, so this is the common path, not an edge.
        # The key is asserted, not just the offset: an unknown fallback key
        # raises ZoneInfoNotFoundError on every briefing run, and a lowercase
        # "utc" resolves to a second, differently-keyed zone object.
        with freeze_time(self.FROZEN):
            clock = resolve_clock(None)

        assert clock.tz.key == "UTC"
        assert clock.date_str == "2026-06-15"
        assert clock.day_of_year == 166
