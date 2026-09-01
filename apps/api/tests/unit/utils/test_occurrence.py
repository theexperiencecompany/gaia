"""Unit tests for the one-second occurrence identity shared by the schedulers."""

from datetime import UTC, datetime, timedelta

import pytest

from app.utils.occurrence import (
    OCCURRENCE_RESOLUTION,
    occurrence_stamp,
    occurrence_window,
    parse_occurrence_stamp,
)

_ARMED = datetime(2026, 8, 30, 10, 53, 56, 465296, tzinfo=UTC)


class TestOccurrenceRoundTrip:
    def test_window_contains_the_instant_the_stamp_was_built_from(self):
        """The encode floors to the second; the window is that floor's inverse."""
        parsed = parse_occurrence_stamp(occurrence_stamp(_ARMED), "task_1")

        window = occurrence_window(parsed)

        assert window["$gte"] <= _ARMED < window["$lt"]

    def test_window_contains_the_millisecond_value_mongo_stores(self):
        """BSON has no finer type than milliseconds, so the armed instant is
        truncated on write — the pin still has to match what came back."""
        stored = _ARMED.replace(microsecond=_ARMED.microsecond // 1000 * 1000)
        parsed = parse_occurrence_stamp(occurrence_stamp(_ARMED), "task_1")

        window = occurrence_window(parsed)

        assert window["$gte"] <= stored < window["$lt"]

    def test_window_floors_a_sub_second_moment(self):
        """The window is built from its own floor, not from the caller's instant.

        A caller that hands over an unfloored moment (a float stamp, a direct
        call) would otherwise get a window starting ABOVE the millisecond-
        truncated value Mongo holds — the same silent no-match the second
        resolution exists to prevent.
        """
        stored = _ARMED.replace(microsecond=_ARMED.microsecond // 1000 * 1000)

        window = occurrence_window(_ARMED)

        assert window["$gte"] <= stored < window["$lt"]

    def test_window_excludes_the_neighbouring_seconds(self):
        window = occurrence_window(_ARMED)

        assert not window["$gte"] <= _ARMED - OCCURRENCE_RESOLUTION < window["$lt"]
        assert not window["$gte"] <= _ARMED + OCCURRENCE_RESOLUTION < window["$lt"]

    def test_window_is_exactly_one_second_wide(self):
        window = occurrence_window(_ARMED)

        assert window["$lt"] - window["$gte"] == timedelta(seconds=1)

    def test_window_is_half_open_at_the_upper_bound(self):
        """A fire on the next whole second belongs to the next occurrence."""
        window = occurrence_window(_ARMED)

        assert window["$lt"] not in (window["$gte"],)
        assert not window["$gte"] <= window["$lt"] < window["$lt"]


class TestOccurrenceStampParsing:
    def test_unstamped_job_is_ungated(self):
        assert parse_occurrence_stamp(None, "task_1") is None

    @pytest.mark.parametrize("raw", ["not-a-number", True, [], {}])
    def test_non_numeric_stamp_degrades_to_ungated(self, raw):
        """A hand-built "run now" context must not crash the fire."""
        assert parse_occurrence_stamp(raw, "task_1") is None

    def test_out_of_range_stamp_degrades_to_ungated(self):
        assert parse_occurrence_stamp(10**20, "task_1") is None

    def test_parsed_stamp_is_utc_aware(self):
        parsed = parse_occurrence_stamp(occurrence_stamp(_ARMED), "task_1")

        assert parsed is not None and parsed.tzinfo is not None
        assert parsed == _ARMED.replace(microsecond=0)
