"""Brutal unit tests for the canonical timezone module (the single source of truth).

Every test imports the real production code in ``app.utils.timezone`` and asserts
on actual behaviour. If a primitive were deleted, the matching test would fail.
"""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.utils.timezone import (
    TIMEZONE_KOLKATA,
    TIMEZONE_LONDON,
    TIMEZONE_NEW_YORK,
    TIMEZONE_TOKYO,
    TIMEZONE_UTC,
    ResolvedTimezone,
    Timezone,
    TimezoneSource,
    format_local_time,
    home_timezone_from_config,
    is_valid_timezone,
    is_within_local_daytime,
    resolve_home_timezone,
)

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Timezone.parse — the one parser. Never raises; offset + IANA + UTC + tzinfo.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimezoneParse:
    @pytest.mark.parametrize(
        "name", ["America/New_York", "Asia/Kolkata", "Europe/London", "Asia/Tokyo", "US/Pacific"]
    )
    def test_iana_name_preserved_and_resolves(self, name: str) -> None:
        tz = Timezone.parse(name)
        assert tz.value == name
        assert tz.tzinfo == ZoneInfo(name)

    @pytest.mark.parametrize(
        "offset_str, delta",
        [
            ("+05:30", timedelta(hours=5, minutes=30)),
            ("-08:00", timedelta(hours=-8)),
            ("+00:00", timedelta(0)),
            ("+14:00", timedelta(hours=14)),
            ("-12:00", timedelta(hours=-12)),
            ("+09:30", timedelta(hours=9, minutes=30)),
            ("-09:30", timedelta(hours=-9, minutes=-30)),
            ("+05:45", timedelta(hours=5, minutes=45)),
        ],
    )
    def test_offset_strings(self, offset_str: str, delta: timedelta) -> None:
        tz = Timezone.parse(offset_str)
        assert tz.value == offset_str
        assert tz.tzinfo.utcoffset(None) == delta

    @pytest.mark.parametrize("variant", ["UTC", "utc", "Utc", "uTc", "  UTC  "])
    def test_utc_variants(self, variant: str) -> None:
        tz = Timezone.parse(variant)
        assert tz.is_utc
        assert tz.tzinfo is UTC

    def test_none_is_utc(self) -> None:
        assert Timezone.parse(None).is_utc

    @pytest.mark.parametrize(
        "garbage", ["", "   ", "Not/A_Zone", "Foo/Bar/Baz", "CEST", "+0530", "+5:30", "5:30", "❌"]
    )
    def test_invalid_falls_back_to_utc_never_raises(self, garbage: str) -> None:
        # The whole point: parsing must never raise into format/notification paths.
        tz = Timezone.parse(garbage)
        assert tz.is_utc

    def test_whitespace_around_iana_is_stripped(self) -> None:
        assert Timezone.parse("  Asia/Kolkata  ").value == "Asia/Kolkata"

    def test_passthrough_timezone_instance_is_idempotent(self) -> None:
        tz = Timezone.parse("Asia/Kolkata")
        assert Timezone.parse(tz) is tz

    def test_parses_builtin_tzinfo_offset(self) -> None:
        tz = Timezone.parse(IST)
        assert tz.value == "+05:30"
        assert tz.tzinfo is IST

    def test_parses_zoneinfo_tzinfo_to_its_key(self) -> None:
        tz = Timezone.parse(ZoneInfo("Europe/Paris"))
        assert tz.value == "Europe/Paris"

    def test_parses_builtin_utc_tzinfo(self) -> None:
        assert Timezone.parse(UTC).is_utc

    def test_utc_classmethod(self) -> None:
        assert Timezone.utc().is_utc and Timezone.utc().tzinfo is UTC


# ---------------------------------------------------------------------------
# Timezone.try_parse — distinguishes "no usable zone" (None) from "UTC".
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimezoneTryParse:
    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_blank_returns_none(self, blank) -> None:
        assert Timezone.try_parse(blank) is None

    @pytest.mark.parametrize("garbage", ["Not/A_Zone", "CEST", "+0530"])
    def test_invalid_returns_none(self, garbage: str) -> None:
        assert Timezone.try_parse(garbage) is None

    def test_explicit_utc_returns_utc_not_none(self) -> None:
        result = Timezone.try_parse("UTC")
        assert result is not None and result.is_utc

    def test_valid_zone_returns_timezone(self) -> None:
        assert Timezone.try_parse("Asia/Kolkata").value == "Asia/Kolkata"

    def test_offset_returns_timezone(self) -> None:
        assert Timezone.try_parse("+05:30").value == "+05:30"


# ---------------------------------------------------------------------------
# Timezone.of_offset — capture a datetime's current offset (DST-correct).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimezoneOfOffset:
    def test_naive_returns_none(self) -> None:
        assert Timezone.of_offset(datetime(2026, 6, 13, 9, 0)) is None

    def test_none_returns_none(self) -> None:
        assert Timezone.of_offset(None) is None

    def test_aware_ist_returns_offset(self) -> None:
        assert Timezone.of_offset(datetime(2026, 6, 13, 9, 0, tzinfo=IST)).value == "+05:30"

    def test_utc_returns_plus_zero(self) -> None:
        assert Timezone.of_offset(datetime(2026, 6, 13, 9, 0, tzinfo=UTC)).value == "+00:00"

    def test_negative_offset(self) -> None:
        tz = timezone(timedelta(hours=-8))
        assert Timezone.of_offset(datetime(2026, 1, 1, tzinfo=tz)).value == "-08:00"

    def test_dst_summer_vs_winter_capture_different_offsets(self) -> None:
        ny = ZoneInfo("America/New_York")
        summer = Timezone.of_offset(datetime(2025, 7, 1, 12, 0, tzinfo=ny))
        winter = Timezone.of_offset(datetime(2025, 1, 1, 12, 0, tzinfo=ny))
        assert summer.value == "-04:00"  # EDT
        assert winter.value == "-05:00"  # EST

    def test_round_trips_through_parse(self) -> None:
        captured = Timezone.of_offset(datetime(2026, 6, 13, 9, 0, tzinfo=IST))
        assert Timezone.parse(captured.value).tzinfo.utcoffset(None) == timedelta(
            hours=5, minutes=30
        )


# ---------------------------------------------------------------------------
# Timezone properties, equality, and behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimezoneProperties:
    def test_is_utc_only_for_utc_value(self) -> None:
        assert Timezone.parse("UTC").is_utc
        assert not Timezone.parse("Asia/Kolkata").is_utc
        # "+00:00" is numerically UTC but a fixed-offset zone, not the "UTC" value.
        assert not Timezone.parse("+00:00").is_utc

    def test_is_offset_only(self) -> None:
        assert Timezone.parse("+05:30").is_offset_only
        assert Timezone.parse("-08:00").is_offset_only
        assert not Timezone.parse("Asia/Kolkata").is_offset_only
        assert not Timezone.parse("UTC").is_offset_only


@pytest.mark.unit
class TestTimezoneEquality:
    def test_equal_by_value(self) -> None:
        assert Timezone.parse("Asia/Kolkata") == Timezone.parse("Asia/Kolkata")

    def test_iana_and_offset_with_same_current_offset_are_not_equal(self) -> None:
        # IST is always +05:30 but the *zone* differs (DST semantics, identity).
        assert Timezone.parse("Asia/Kolkata") != Timezone.parse("+05:30")

    def test_not_equal_to_plain_string(self) -> None:
        assert Timezone.parse("Asia/Kolkata") != "Asia/Kolkata"

    def test_hashable_dedupes_in_set(self) -> None:
        zones = {Timezone.parse("UTC"), Timezone.parse("UTC"), Timezone.parse("Asia/Kolkata")}
        assert len(zones) == 2


@pytest.mark.unit
class TestTimezoneNowLocalizeFormat:
    def test_now_is_aware_in_zone(self) -> None:
        now = Timezone.parse("Asia/Kolkata").now()
        assert now.tzinfo is not None
        assert now.utcoffset() == timedelta(hours=5, minutes=30)

    def test_localize_converts_instant(self) -> None:
        instant = datetime(2026, 6, 13, 0, 0, tzinfo=UTC)
        local = Timezone.parse("Asia/Kolkata").localize(instant)
        assert (local.hour, local.minute) == (5, 30)

    def test_format_strips_leading_zero(self) -> None:
        instant = datetime(2026, 6, 13, 3, 5, tzinfo=UTC)  # 03:05 UTC
        assert Timezone.parse("UTC").format(instant, "%I:%M %p").startswith("3:05 AM")

    def test_format_is_offset_aware(self) -> None:
        # Regression: the old utils/timezone.parse_timezone could NOT parse offsets
        # and silently formatted in UTC. The unified parser must honour "+05:30".
        instant = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)  # 12:00 UTC -> 17:30 IST
        assert "5:30 PM" in Timezone.parse("+05:30").format(instant, "%I:%M %p")


# ---------------------------------------------------------------------------
# is_valid_timezone
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsValidTimezone:
    @pytest.mark.parametrize("ok", ["Asia/Kolkata", "UTC", "+05:30", "-08:00"])
    def test_valid(self, ok: str) -> None:
        assert is_valid_timezone(ok) is True

    @pytest.mark.parametrize("bad", [None, "", "   ", "Not/A_Zone", "+0530", "CEST"])
    def test_invalid(self, bad) -> None:
        assert is_valid_timezone(bad) is False


# ---------------------------------------------------------------------------
# resolve_home_timezone — the ONE precedence rule (+ stored-"UTC" heal)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveHomeTimezone:
    def test_real_stored_zone_wins_no_heal(self) -> None:
        r = resolve_home_timezone("America/New_York", "Asia/Kolkata")
        assert r.timezone.value == "America/New_York"
        assert r.source is TimezoneSource.USER_PROFILE
        assert r.should_heal is False

    def test_stored_utc_is_healed_by_valid_header(self) -> None:
        r = resolve_home_timezone("UTC", "Asia/Kolkata")
        assert r.timezone.value == "Asia/Kolkata"
        assert r.source is TimezoneSource.X_TIMEZONE_HEADER
        assert r.should_heal is True

    def test_empty_stored_filled_by_valid_header(self) -> None:
        r = resolve_home_timezone(None, "Asia/Kolkata")
        assert r.timezone.value == "Asia/Kolkata"
        assert r.source is TimezoneSource.X_TIMEZONE_HEADER
        assert r.should_heal is True

    def test_invalid_stored_treated_as_unset_and_healed(self) -> None:
        r = resolve_home_timezone("Garbage/Zone", "Asia/Kolkata")
        assert r.timezone.value == "Asia/Kolkata"
        assert r.should_heal is True

    def test_genuine_utc_preserved_when_no_better_signal(self) -> None:
        r = resolve_home_timezone("UTC", "UTC")
        assert r.timezone.is_utc
        assert r.source is TimezoneSource.FALLBACK_UTC
        assert r.should_heal is False

    def test_stored_utc_with_garbage_header_stays_utc(self) -> None:
        r = resolve_home_timezone("UTC", "Not/A_Zone")
        assert r.timezone.is_utc
        assert r.should_heal is False

    def test_nothing_known_falls_back_to_utc(self) -> None:
        r = resolve_home_timezone("", "")
        assert r.timezone.is_utc
        assert r.source is TimezoneSource.FALLBACK_UTC
        assert r.should_heal is False

    def test_utc_header_never_heals(self) -> None:
        # A UTC header is not a confident signal; it must not overwrite an empty
        # profile with "UTC" and it must not heal.
        r = resolve_home_timezone(None, "UTC")
        assert r.timezone.is_utc
        assert r.should_heal is False

    def test_offset_header_is_accepted_and_heals(self) -> None:
        r = resolve_home_timezone(None, "+05:30")
        assert r.timezone.value == "+05:30"
        assert r.source is TimezoneSource.X_TIMEZONE_HEADER
        assert r.should_heal is True

    def test_whitespace_only_inputs_fall_back(self) -> None:
        r = resolve_home_timezone("   ", "   ")
        assert r.timezone.is_utc and r.source is TimezoneSource.FALLBACK_UTC

    def test_returns_resolved_dataclass(self) -> None:
        assert isinstance(resolve_home_timezone("Asia/Kolkata", None), ResolvedTimezone)


# ---------------------------------------------------------------------------
# Agent-config accessors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHomeTimezoneFromConfig:
    def test_reads_user_timezone(self) -> None:
        tz = home_timezone_from_config({"configurable": {"user_timezone": "+05:30"}})
        assert tz.value == "+05:30"

    def test_missing_user_timezone_is_utc(self) -> None:
        assert home_timezone_from_config({"configurable": {}}).is_utc

    def test_missing_configurable_is_utc(self) -> None:
        assert home_timezone_from_config({}).is_utc


# ---------------------------------------------------------------------------
# format_local_time / is_within_local_daytime (string-in convenience wrappers)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatLocalTime:
    def test_iana_zone(self) -> None:
        instant = datetime(2026, 6, 13, 0, 0, tzinfo=UTC)  # 05:30 IST
        assert "5:30 AM" in format_local_time(instant, "Asia/Kolkata")

    def test_offset_zone(self) -> None:
        instant = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)  # 17:30 +05:30
        assert "5:30 PM" in format_local_time(instant, "+05:30")

    def test_invalid_zone_falls_back_to_utc(self) -> None:
        instant = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
        assert "12:00 PM" in format_local_time(instant, "Not/A_Zone")

    def test_none_zone_is_utc(self) -> None:
        instant = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
        assert "12:00 PM" in format_local_time(instant, None)


@pytest.mark.unit
class TestIsWithinLocalDaytime:
    def test_inside_window(self) -> None:
        instant = datetime(2026, 6, 13, 6, 0, tzinfo=UTC)  # 11:30 IST
        assert is_within_local_daytime(instant, "Asia/Kolkata", 9, 21) is True

    def test_outside_window(self) -> None:
        instant = datetime(2026, 6, 13, 20, 0, tzinfo=UTC)  # 01:30 IST next day
        assert is_within_local_daytime(instant, "Asia/Kolkata", 9, 21) is False

    def test_offset_zone(self) -> None:
        instant = datetime(2026, 6, 13, 4, 0, tzinfo=UTC)  # 09:30 +05:30
        assert is_within_local_daytime(instant, "+05:30", 9, 21) is True


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModuleConstants:
    def test_utc_constant_is_builtin_utc(self) -> None:
        assert TIMEZONE_UTC is UTC

    def test_named_constants(self) -> None:
        assert TIMEZONE_KOLKATA == "Asia/Kolkata"
        assert TIMEZONE_NEW_YORK == "America/New_York"
        assert TIMEZONE_LONDON == "Europe/London"
        assert TIMEZONE_TOKYO == "Asia/Tokyo"
