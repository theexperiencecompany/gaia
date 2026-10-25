"""Unit tests for calendar Pydantic models."""

from pydantic import ValidationError
import pytest

from app.models.calendar_models import (
    AddRecurrenceInput,
    CalendarEventsQueryRequest,
    EventCreateRequest,
    RecurrenceData,
    RecurrenceRule,
)


class TestCalendarEventsQueryRequest:
    @pytest.mark.parametrize(
        "date_val",
        ["01-15-2025", "2025/01/15", "Jan 15, 2025", "not-a-date", "2025-13-01"],
    )
    def test_invalid_date_formats(self, date_val):
        with pytest.raises(ValidationError):
            CalendarEventsQueryRequest(selected_calendars=["cal1"], start_date=date_val)

    def test_invalid_date_value(self):
        with pytest.raises(ValidationError):
            CalendarEventsQueryRequest(selected_calendars=["cal1"], start_date="2025-02-30")

    def test_none_dates_pass_through(self):
        m = CalendarEventsQueryRequest(selected_calendars=["cal1"], start_date=None, end_date=None)
        assert m.start_date is None
        assert m.end_date is None

    def test_invalid_start_date_exact_message(self):
        with pytest.raises(
            ValidationError,
            match=r"Invalid date format: 2025/01/15\. Use YYYY-MM-DD format\.",
        ):
            CalendarEventsQueryRequest(selected_calendars=["cal1"], start_date="2025/01/15")

    def test_invalid_date_value_exact_message(self):
        with pytest.raises(ValidationError, match=r"Invalid date: 2025-02-30"):
            CalendarEventsQueryRequest(selected_calendars=["cal1"], end_date="2025-02-30")


class TestRecurrenceRule:
    def test_count_and_until_exclusive(self):
        with pytest.raises(ValidationError, match="Cannot specify both"):
            RecurrenceRule(frequency="DAILY", count=5, until="2025-12-31")

    @pytest.mark.parametrize("bad_day", ["XX", "monday", "M", ""])
    def test_invalid_by_day(self, bad_day):
        with pytest.raises(ValidationError, match="Invalid day value"):
            RecurrenceRule(frequency="WEEKLY", by_day=[bad_day])

    @pytest.mark.parametrize("bad_day", [0, 32, -1])
    def test_invalid_by_month_day(self, bad_day):
        with pytest.raises(ValidationError, match="Invalid day of month"):
            RecurrenceRule(frequency="MONTHLY", by_month_day=[bad_day])

    @pytest.mark.parametrize("bad_month", [0, 13, -1])
    def test_invalid_by_month(self, bad_month):
        with pytest.raises(ValidationError, match="Invalid month"):
            RecurrenceRule(frequency="YEARLY", by_month=[bad_month])

    def test_monthly_cannot_have_by_day_and_by_month_day(self):
        with pytest.raises(ValidationError, match="Cannot specify both"):
            RecurrenceRule(frequency="MONTHLY", by_day=["MO"], by_month_day=[15])

    def test_invalid_until_format(self):
        with pytest.raises(ValidationError, match="Invalid 'until' date format"):
            RecurrenceRule(frequency="DAILY", until="not-a-date")

    @pytest.mark.parametrize("bad_date", ["01-01-2025", "2025/01/01", "not-a-date"])
    def test_invalid_exclude_dates(self, bad_date):
        with pytest.raises(ValidationError):
            RecurrenceRule(frequency="DAILY", exclude_dates=[bad_date])

    @pytest.mark.parametrize("bad_date", ["01-01-2025", "2025/01/01", "not-a-date"])
    def test_invalid_include_dates(self, bad_date):
        with pytest.raises(ValidationError):
            RecurrenceRule(frequency="DAILY", include_dates=[bad_date])

    def test_invalid_exclude_date_value(self):
        with pytest.raises(ValidationError):
            RecurrenceRule(frequency="DAILY", exclude_dates=["2025-02-30"])

    def test_invalid_exclude_date_format_exact_message(self):
        with pytest.raises(
            ValidationError,
            match=r"Invalid date format: not-a-date\. Use YYYY-MM-DD format\.",
        ):
            RecurrenceRule(frequency="DAILY", exclude_dates=["not-a-date"])

    def test_invalid_include_date_value_exact_message(self):
        with pytest.raises(ValidationError, match=r"Invalid date: 2025-02-31"):
            RecurrenceRule(frequency="DAILY", include_dates=["2025-02-31"])


class TestRecurrenceRuleToRruleString:
    def test_simple_daily(self):
        m = RecurrenceRule(frequency="DAILY")
        assert m.to_rrule_string() == "RRULE:FREQ=DAILY"

    def test_with_until_datetime_utc_exact_value(self):
        m = RecurrenceRule(frequency="DAILY", until="2025-12-31T23:59:59+00:00")
        assert m.to_rrule_string() == "RRULE:FREQ=DAILY;UNTIL=20251231T235959Z"

    def test_with_until_datetime_non_utc_exact_value(self):
        """An offset is converted to UTC, not relabelled: 10:00+05:30 is 04:30Z."""
        m = RecurrenceRule(frequency="DAILY", until="2025-06-15T10:00:00+05:30")
        assert m.to_rrule_string() == "RRULE:FREQ=DAILY;UNTIL=20250615T043000Z"

    def test_with_until_datetime_z_suffix_exact_value(self):
        m = RecurrenceRule(frequency="DAILY", until="2025-12-31T23:59:59Z")
        assert m.to_rrule_string() == "RRULE:FREQ=DAILY;UNTIL=20251231T235959Z"

    def test_z_suffix_and_plus_zero_produce_same_compact_value(self):
        z = RecurrenceRule(frequency="DAILY", until="2025-12-31T23:59:59Z").to_rrule_string()
        plus = RecurrenceRule(
            frequency="DAILY", until="2025-12-31T23:59:59+00:00"
        ).to_rrule_string()
        assert z == plus == "RRULE:FREQ=DAILY;UNTIL=20251231T235959Z"


class TestUntilRruleValueUnparseableFallbacks:
    """The RFC 5545 formatter's fallbacks for until values that slip past validation: a bare date degrades to its compact form, an unparseable datetime passes through verbatim."""

    def test_unparseable_bare_date_degrades_to_its_compact_form(self):
        m = RecurrenceRule.model_construct(frequency="DAILY", until="31-12-2025")
        assert "UNTIL=31122025" in m.to_rrule_string()

    def test_unparseable_datetime_is_passed_through_verbatim(self):
        m = RecurrenceRule.model_construct(frequency="DAILY", until="31/12/2025T10:00")
        assert "UNTIL=31/12/2025T10:00" in m.to_rrule_string()


class TestRecurrenceData:
    def test_to_google_calendar_format_basic(self):
        rule = RecurrenceRule(frequency="WEEKLY", by_day=["MO"])
        m = RecurrenceData(rrule=rule)
        result = m.to_google_calendar_format()
        assert len(result) == 1
        assert result[0].startswith("RRULE:")

    def test_to_google_calendar_format_with_include_dates(self):
        rule = RecurrenceRule(frequency="DAILY", include_dates=["2025-06-01", "2025-07-01"])
        m = RecurrenceData(rrule=rule)
        result = m.to_google_calendar_format()
        assert len(result) == 2
        rdate = [r for r in result if r.startswith("RDATE")]
        assert len(rdate) == 1
        assert "20250601" in rdate[0]
        assert "20250701" in rdate[0]

    def test_to_google_calendar_format_with_exclude_dates(self):
        rule = RecurrenceRule(frequency="DAILY", exclude_dates=["2025-06-10"])
        m = RecurrenceData(rrule=rule)
        result = m.to_google_calendar_format()
        exdate = [r for r in result if r.startswith("EXDATE")]
        assert len(exdate) == 1
        assert "20250610" in exdate[0]

    def test_to_google_calendar_format_with_both_dates(self):
        rule = RecurrenceRule(
            frequency="DAILY",
            include_dates=["2025-01-01"],
            exclude_dates=["2025-01-02"],
        )
        m = RecurrenceData(rrule=rule)
        result = m.to_google_calendar_format()
        assert len(result) == 3


class TestEventCreateRequest:
    def test_valid_unpadded_date_is_accepted(self):
        """The fromisoformat parser rejects "2025-6-1"; the strptime %Y-%m-%d fallback accepts it."""
        m = EventCreateRequest(
            summary="Holiday",
            start="2025-6-1",
            end="2025-6-1",
            is_all_day=True,
        )
        assert m.is_all_day is True

    def test_start_after_end_raises(self):
        with pytest.raises(ValidationError, match="Start time must be before end time"):
            EventCreateRequest(
                summary="Bad",
                start="2025-06-01T12:00:00",
                end="2025-06-01T10:00:00",
            )

    def test_start_equals_end_raises(self):
        with pytest.raises(ValidationError, match="Start time must be before end time"):
            EventCreateRequest(
                summary="Bad",
                start="2025-06-01T10:00:00",
                end="2025-06-01T10:00:00",
            )

    def test_invalid_time_format(self):
        with pytest.raises(ValidationError, match="must be in ISO format"):
            EventCreateRequest(summary="Bad", start="not-a-time", end="also-bad")

    def test_all_day_event_start_after_end_ok(self):
        # For all-day events, start >= end is allowed (no time comparison)
        m = EventCreateRequest(
            summary="Holiday",
            start="2025-06-02",
            end="2025-06-01",
            is_all_day=True,
        )
        assert m.is_all_day is True


class TestAddRecurrenceInput:
    def test_count_and_until_exclusive(self):
        with pytest.raises(ValidationError, match="Cannot specify both"):
            AddRecurrenceInput(
                event_id="evt1",
                frequency="DAILY",
                count=5,
                until_date="2025-12-31",
            )

    @pytest.mark.parametrize("bad_day", ["XX", "monday", ""])
    def test_invalid_by_day(self, bad_day):
        with pytest.raises(ValidationError, match="Invalid day"):
            AddRecurrenceInput(event_id="evt1", frequency="WEEKLY", by_day=[bad_day])
