"""Unit tests for calendar Pydantic models."""

from datetime import datetime

from pydantic import ValidationError
import pytest

from app.models.calendar_models import (
    AddRecurrenceInput,
    BaseCalendarEvent,
    BatchEventCreateRequest,
    BatchEventDeleteRequest,
    BatchEventUpdateRequest,
    CalendarEventsQueryRequest,
    # CalendarEventToolRequest,  # Unwired as of 2026-06; see calendar_models.py
    CalendarPreferencesUpdateRequest,
    CreateEventInput,
    DeleteEventInput,
    EventCreateRequest,
    EventDeleteRequest,
    EventReference,
    EventUpdateRequest,
    FetchEventsInput,
    FindEventInput,
    GetDaySummaryInput,
    GetEventInput,
    ListCalendarsInput,
    PatchEventInput,
    RecurrenceData,
    RecurrenceRule,
    SingleEventInput,
)


# ---------------------------------------------------------------------------
# CalendarPreferencesUpdateRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCalendarPreferencesUpdateRequest:
    def test_valid(self):
        m = CalendarPreferencesUpdateRequest(selected_calendars=["cal1", "cal2"])
        assert m.selected_calendars == ["cal1", "cal2"]

    def test_empty_list(self):
        m = CalendarPreferencesUpdateRequest(selected_calendars=[])
        assert m.selected_calendars == []

    def test_missing_field(self):
        with pytest.raises(ValidationError):
            CalendarPreferencesUpdateRequest()


# ---------------------------------------------------------------------------
# CalendarEventsQueryRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCalendarEventsQueryRequest:
    def test_valid_minimal(self):
        m = CalendarEventsQueryRequest(selected_calendars=["primary"])
        assert m.selected_calendars == ["primary"]
        assert m.start_date is None
        assert m.end_date is None
        assert m.fetch_all is True
        assert m.max_results is None

    def test_valid_full(self):
        m = CalendarEventsQueryRequest(
            selected_calendars=["cal1"],
            start_date="2025-01-15",
            end_date="2025-02-15",
            fetch_all=False,
            max_results=50,
        )
        assert m.start_date == "2025-01-15"
        assert m.end_date == "2025-02-15"
        assert m.fetch_all is False
        assert m.max_results == 50

    @pytest.mark.parametrize(
        "date_val",
        ["2025-01-15", "2000-12-31", "2099-06-01"],
    )
    def test_valid_date_formats(self, date_val):
        m = CalendarEventsQueryRequest(selected_calendars=["cal1"], start_date=date_val)
        assert m.start_date == date_val

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

    def test_max_results_boundaries(self):
        m = CalendarEventsQueryRequest(selected_calendars=["cal1"], max_results=1)
        assert m.max_results == 1

        m = CalendarEventsQueryRequest(selected_calendars=["cal1"], max_results=250)
        assert m.max_results == 250

    @pytest.mark.parametrize("val", [0, -1, 251, 500])
    def test_max_results_out_of_range(self, val):
        with pytest.raises(ValidationError):
            CalendarEventsQueryRequest(selected_calendars=["cal1"], max_results=val)


# ---------------------------------------------------------------------------
# EventDeleteRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEventDeleteRequest:
    def test_valid_minimal(self):
        m = EventDeleteRequest(event_id="evt1")
        assert m.event_id == "evt1"
        assert m.calendar_id == "primary"
        assert m.summary is None

    def test_valid_full(self):
        m = EventDeleteRequest(event_id="evt1", calendar_id="work", summary="Meeting")
        assert m.calendar_id == "work"
        assert m.summary == "Meeting"

    def test_missing_event_id(self):
        with pytest.raises(ValidationError):
            EventDeleteRequest()


# ---------------------------------------------------------------------------
# RecurrenceRule
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRecurrenceRule:
    def test_valid_daily(self):
        m = RecurrenceRule(frequency="DAILY")
        assert m.frequency == "DAILY"
        assert m.interval == 1

    def test_valid_weekly_with_days(self):
        m = RecurrenceRule(frequency="WEEKLY", by_day=["MO", "WE", "FR"])
        assert m.by_day == ["MO", "WE", "FR"]

    def test_valid_monthly_with_month_day(self):
        m = RecurrenceRule(frequency="MONTHLY", by_month_day=[1, 15])
        assert m.by_month_day == [1, 15]

    def test_valid_yearly_with_month(self):
        m = RecurrenceRule(frequency="YEARLY", by_month=[1, 6, 12])
        assert m.by_month == [1, 6, 12]

    def test_valid_with_count(self):
        m = RecurrenceRule(frequency="DAILY", count=10)
        assert m.count == 10

    def test_valid_with_until_date(self):
        m = RecurrenceRule(frequency="DAILY", until="2025-12-31")
        assert m.until == "2025-12-31"

    def test_valid_with_until_datetime(self):
        m = RecurrenceRule(frequency="DAILY", until="2025-12-31T23:59:59+00:00")
        assert m.until == "2025-12-31T23:59:59+00:00"

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

    @pytest.mark.parametrize("freq", ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"])
    def test_valid_frequencies(self, freq):
        m = RecurrenceRule(frequency=freq)
        assert m.frequency == freq

    def test_invalid_frequency(self):
        with pytest.raises(ValidationError):
            RecurrenceRule(frequency="HOURLY")

    def test_interval_must_be_ge_1(self):
        with pytest.raises(ValidationError):
            RecurrenceRule(frequency="DAILY", interval=0)

    def test_count_must_be_ge_1(self):
        with pytest.raises(ValidationError):
            RecurrenceRule(frequency="DAILY", count=0)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            RecurrenceRule(frequency="DAILY", unknown_field="x")

    def test_exclude_dates_valid(self):
        m = RecurrenceRule(frequency="DAILY", exclude_dates=["2025-01-01", "2025-06-15"])
        assert m.exclude_dates == ["2025-01-01", "2025-06-15"]

    def test_include_dates_valid(self):
        m = RecurrenceRule(frequency="DAILY", include_dates=["2025-03-01"])
        assert m.include_dates == ["2025-03-01"]

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


# ---------------------------------------------------------------------------
# RecurrenceRule.to_rrule_string
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRecurrenceRuleToRruleString:
    def test_simple_daily(self):
        m = RecurrenceRule(frequency="DAILY")
        assert m.to_rrule_string() == "RRULE:FREQ=DAILY"

    def test_with_interval(self):
        m = RecurrenceRule(frequency="WEEKLY", interval=2, by_day=["MO", "FR"])
        result = m.to_rrule_string()
        assert "FREQ=WEEKLY" in result
        assert "INTERVAL=2" in result
        assert "BYDAY=MO,FR" in result

    def test_with_count(self):
        m = RecurrenceRule(frequency="DAILY", count=5)
        assert "COUNT=5" in m.to_rrule_string()

    def test_with_until_date(self):
        m = RecurrenceRule(frequency="DAILY", until="2025-12-31")
        result = m.to_rrule_string()
        assert "UNTIL=20251231" in result

    def test_with_until_datetime_utc(self):
        m = RecurrenceRule(frequency="DAILY", until="2025-12-31T23:59:59+00:00")
        result = m.to_rrule_string()
        assert "UNTIL=" in result
        assert "Z" in result

    def test_with_by_month_day(self):
        m = RecurrenceRule(frequency="MONTHLY", by_month_day=[1, 15])
        assert "BYMONTHDAY=1,15" in m.to_rrule_string()

    def test_with_by_month(self):
        m = RecurrenceRule(frequency="YEARLY", by_month=[3, 9])
        assert "BYMONTH=3,9" in m.to_rrule_string()

    def test_interval_1_not_in_output(self):
        m = RecurrenceRule(frequency="DAILY", interval=1)
        assert "INTERVAL" not in m.to_rrule_string()

    def test_until_datetime_non_utc(self):
        m = RecurrenceRule(frequency="DAILY", until="2025-06-15T10:00:00+05:30")
        result = m.to_rrule_string()
        assert "UNTIL=" in result


# ---------------------------------------------------------------------------
# RecurrenceData
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRecurrenceData:
    def test_valid(self):
        rule = RecurrenceRule(frequency="DAILY")
        m = RecurrenceData(rrule=rule)
        assert m.rrule.frequency == "DAILY"

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

    def test_extra_fields_forbidden(self):
        rule = RecurrenceRule(frequency="DAILY")
        with pytest.raises(ValidationError):
            RecurrenceData(rrule=rule, unknown="x")


# ---------------------------------------------------------------------------
# EventUpdateRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEventUpdateRequest:
    def test_valid_minimal(self):
        m = EventUpdateRequest(event_id="evt1")
        assert m.event_id == "evt1"
        assert m.calendar_id == "primary"
        assert m.summary is None

    def test_valid_full(self):
        rule = RecurrenceRule(frequency="WEEKLY", by_day=["TU"])
        m = EventUpdateRequest(
            event_id="evt1",
            calendar_id="work",
            summary="Updated",
            description="Desc",
            start="2025-06-01T10:00:00",
            end="2025-06-01T11:00:00",
            is_all_day=False,
            timezone="America/New_York",
            timezone_offset="+05:00",
            original_summary="Original",
            recurrence=RecurrenceData(rrule=rule),
        )
        assert m.summary == "Updated"
        assert m.recurrence is not None

    def test_missing_event_id(self):
        with pytest.raises(ValidationError):
            EventUpdateRequest()


# ---------------------------------------------------------------------------
# BaseCalendarEvent
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBaseCalendarEvent:
    def test_valid_minimal(self):
        m = BaseCalendarEvent(summary="Test")
        assert m.summary == "Test"
        assert m.description == ""
        assert m.is_all_day is False
        assert m.calendar_id is None
        assert m.recurrence is None
        assert m.attendees is None
        assert m.create_meeting_room is False

    def test_extra_fields_ignored(self):
        m = BaseCalendarEvent(summary="Test", unknown_field="ignored")
        assert not hasattr(m, "unknown_field")

    def test_missing_summary(self):
        with pytest.raises(ValidationError):
            BaseCalendarEvent()


# ---------------------------------------------------------------------------
# EventCreateRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEventCreateRequest:
    def test_valid_timed(self):
        m = EventCreateRequest(
            summary="Meeting",
            start="2025-06-01T10:00:00",
            end="2025-06-01T11:00:00",
        )
        assert m.start == "2025-06-01T10:00:00"

    def test_valid_all_day(self):
        m = EventCreateRequest(
            summary="Holiday",
            start="2025-06-01",
            end="2025-06-01",
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
        with pytest.raises(ValidationError):
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

    def test_valid_with_timezone(self):
        m = EventCreateRequest(
            summary="Meeting",
            start="2025-06-01T10:00:00+05:30",
            end="2025-06-01T11:00:00+05:30",
            timezone="Asia/Kolkata",
        )
        assert m.timezone == "Asia/Kolkata"


# ---------------------------------------------------------------------------
# BatchEventCreateRequest / BatchEventUpdateRequest / BatchEventDeleteRequest
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBatchRequests:
    def test_batch_create(self):
        event = EventCreateRequest(
            summary="A", start="2025-06-01T10:00:00", end="2025-06-01T11:00:00"
        )
        m = BatchEventCreateRequest(events=[event])
        assert len(m.events) == 1

    def test_batch_update(self):
        event = EventUpdateRequest(event_id="evt1", summary="Updated")
        m = BatchEventUpdateRequest(events=[event])
        assert len(m.events) == 1

    def test_batch_delete(self):
        event = EventDeleteRequest(event_id="evt1")
        m = BatchEventDeleteRequest(events=[event])
        assert len(m.events) == 1

    def test_batch_create_empty(self):
        # Pydantic allows empty list since there's no min_length constraint
        m = BatchEventCreateRequest(events=[])
        assert m.events == []


# ---------------------------------------------------------------------------
# SingleEventInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSingleEventInput:
    def test_valid_minimal(self):
        m = SingleEventInput(summary="Test", start_datetime="2025-06-01T10:00:00")
        assert m.summary == "Test"
        assert m.duration_hours == 0
        assert m.duration_minutes == 30
        assert m.calendar_id == "primary"
        assert m.is_all_day is False
        assert m.create_meeting_room is False

    def test_valid_full(self):
        m = SingleEventInput(
            summary="Full Event",
            start_datetime="2025-06-01T10:00:00",
            duration_hours=2,
            duration_minutes=15,
            calendar_id="work",
            description="Description",
            location="Office",
            attendees=["a@b.com"],
            is_all_day=False,
            create_meeting_room=True,
        )
        assert m.duration_hours == 2
        assert m.location == "Office"

    @pytest.mark.parametrize("hours", [-1, 24])
    def test_duration_hours_out_of_range(self, hours):
        with pytest.raises(ValidationError):
            SingleEventInput(
                summary="Bad",
                start_datetime="2025-06-01T10:00:00",
                duration_hours=hours,
            )

    @pytest.mark.parametrize("minutes", [-1, 60])
    def test_duration_minutes_out_of_range(self, minutes):
        with pytest.raises(ValidationError):
            SingleEventInput(
                summary="Bad",
                start_datetime="2025-06-01T10:00:00",
                duration_minutes=minutes,
            )


# ---------------------------------------------------------------------------
# CreateEventInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCreateEventInput:
    def test_valid(self):
        event = SingleEventInput(summary="A", start_datetime="2025-06-01T10:00:00")
        m = CreateEventInput(events=[event])
        assert len(m.events) == 1
        assert m.confirm_immediately is False

    def test_confirm_immediately_true(self):
        event = SingleEventInput(summary="A", start_datetime="2025-06-01T10:00:00")
        m = CreateEventInput(events=[event], confirm_immediately=True)
        assert m.confirm_immediately is True

    def test_missing_events(self):
        with pytest.raises(ValidationError):
            CreateEventInput()


# ---------------------------------------------------------------------------
# ListCalendarsInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestListCalendarsInput:
    def test_default(self):
        m = ListCalendarsInput()
        assert m.short is True

    def test_short_false(self):
        m = ListCalendarsInput(short=False)
        assert m.short is False


# ---------------------------------------------------------------------------
# FetchEventsInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFetchEventsInput:
    def test_defaults(self):
        m = FetchEventsInput()
        assert m.calendar_ids == []
        assert m.time_min is None
        assert m.time_max is None
        assert m.max_results == 30

    def test_max_results_boundaries(self):
        m = FetchEventsInput(max_results=1)
        assert m.max_results == 1
        m = FetchEventsInput(max_results=250)
        assert m.max_results == 250

    @pytest.mark.parametrize("val", [0, -1, 251])
    def test_max_results_out_of_range(self, val):
        with pytest.raises(ValidationError):
            FetchEventsInput(max_results=val)


# ---------------------------------------------------------------------------
# GetDaySummaryInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetDaySummaryInput:
    def test_default_date_is_today(self):
        m = GetDaySummaryInput()
        assert m.date == datetime.now().strftime("%Y-%m-%d")

    def test_custom_date(self):
        m = GetDaySummaryInput(date="2025-03-15")
        assert m.date == "2025-03-15"


# ---------------------------------------------------------------------------
# FindEventInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFindEventInput:
    def test_valid_minimal(self):
        m = FindEventInput(query="standup")
        assert m.query == "standup"
        assert m.calendar_id == "primary"

    def test_valid_full(self):
        m = FindEventInput(
            query="standup",
            calendar_id="work",
            time_min="2025-01-01T00:00:00",
            time_max="2025-12-31T23:59:59",
        )
        assert m.calendar_id == "work"

    def test_missing_query(self):
        with pytest.raises(ValidationError):
            FindEventInput()


# ---------------------------------------------------------------------------
# EventReference / GetEventInput / DeleteEventInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEventReference:
    def test_valid_minimal(self):
        m = EventReference(event_id="evt1")
        assert m.event_id == "evt1"
        assert m.calendar_id == "primary"

    def test_valid_with_calendar(self):
        m = EventReference(event_id="evt1", calendar_id="work")
        assert m.calendar_id == "work"


@pytest.mark.unit
class TestGetEventInput:
    def test_valid(self):
        ref = EventReference(event_id="evt1")
        m = GetEventInput(events=[ref])
        assert len(m.events) == 1


@pytest.mark.unit
class TestDeleteEventInput:
    def test_valid(self):
        ref = EventReference(event_id="evt1")
        m = DeleteEventInput(events=[ref])
        assert m.send_updates == "all"

    def test_custom_send_updates(self):
        ref = EventReference(event_id="evt1")
        m = DeleteEventInput(events=[ref], send_updates="none")
        assert m.send_updates == "none"


# ---------------------------------------------------------------------------
# PatchEventInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPatchEventInput:
    def test_valid_minimal(self):
        m = PatchEventInput(event_id="evt1")
        assert m.event_id == "evt1"
        assert m.calendar_id == "primary"
        assert m.summary is None

    def test_valid_full(self):
        m = PatchEventInput(
            event_id="evt1",
            calendar_id="work",
            summary="New Title",
            description="New Desc",
            start_datetime="2025-06-01T10:00:00",
            end_datetime="2025-06-01T11:00:00",
            location="Room A",
            attendees=["a@b.com"],
            send_updates="externalOnly",
        )
        assert m.location == "Room A"
        assert m.send_updates == "externalOnly"


# ---------------------------------------------------------------------------
# AddRecurrenceInput
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAddRecurrenceInput:
    def test_valid_minimal(self):
        m = AddRecurrenceInput(event_id="evt1", frequency="DAILY")
        assert m.interval == 1
        assert m.count == 0
        assert m.until_date == ""
        assert m.by_day == []

    def test_valid_full(self):
        m = AddRecurrenceInput(
            event_id="evt1",
            calendar_id="work",
            frequency="WEEKLY",
            interval=2,
            count=10,
            by_day=["MO", "FR"],
        )
        assert m.interval == 2
        assert m.by_day == ["MO", "FR"]

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

    def test_interval_min_boundary(self):
        m = AddRecurrenceInput(event_id="evt1", frequency="DAILY", interval=1)
        assert m.interval == 1

    def test_interval_zero_invalid(self):
        with pytest.raises(ValidationError):
            AddRecurrenceInput(event_id="evt1", frequency="DAILY", interval=0)

    @pytest.mark.parametrize("freq", ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"])
    def test_valid_frequencies(self, freq):
        m = AddRecurrenceInput(event_id="evt1", frequency=freq)
        assert m.frequency == freq

    def test_invalid_frequency(self):
        with pytest.raises(ValidationError):
            AddRecurrenceInput(event_id="evt1", frequency="HOURLY")
