"""Unit tests for calendar utility functions."""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.utils.calendar_utils import (
    extract_event_dates,
    fetch_calendar_color,
    fetch_same_day_events,
    resolve_timezone,
)

# Patch targets — these functions are imported inline inside the production
# code, so we patch them at the source module.
_LIST_CALENDARS = "app.services.calendar_service.list_calendars"
_GET_CALENDAR_EVENTS = "app.services.calendar_service.get_calendar_events"


# ---------------------------------------------------------------------------
# resolve_timezone
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveTimezone:
    def test_canonical_timezone_returned_unchanged(self) -> None:
        result = resolve_timezone("America/New_York")
        assert result == "America/New_York"

    def test_legacy_alias_accepted(self) -> None:
        # Pendulum accepts legacy aliases — verify they pass validation
        result = resolve_timezone("US/Eastern")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_utc_timezone(self) -> None:
        result = resolve_timezone("UTC")
        assert result == "UTC"

    def test_invalid_timezone_raises_http_exception(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            resolve_timezone("Not/A/Timezone")
        assert exc_info.value.status_code == 400
        assert "Invalid timezone" in exc_info.value.detail

    def test_empty_string_raises_http_exception(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            resolve_timezone("")
        assert exc_info.value.status_code == 400

    def test_error_detail_contains_timezone_name(self) -> None:
        bad_tz = "Fake/Zone"
        with pytest.raises(HTTPException) as exc_info:
            resolve_timezone(bad_tz)
        assert bad_tz in exc_info.value.detail


# ---------------------------------------------------------------------------
# fetch_calendar_color
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchCalendarColor:
    @patch(_LIST_CALENDARS)
    def test_success_returns_summary_and_color(
        self, mock_list_calendars: MagicMock
    ) -> None:
        mock_list_calendars.return_value = {
            "items": [
                {
                    "id": "cal-123",
                    "summary": "Work",
                    "backgroundColor": "#ff0000",
                },
            ]
        }
        name, color = fetch_calendar_color("cal-123", "user-1")
        assert name == "Work"
        assert color == "#ff0000"
        mock_list_calendars.assert_called_once_with("user-1")

    @patch(_LIST_CALENDARS)
    def test_empty_items_returns_defaults(self, mock_list_calendars: MagicMock) -> None:
        mock_list_calendars.return_value = {"items": []}
        name, color = fetch_calendar_color("cal-missing", "user-1")
        assert name == "Calendar"
        assert color == "#00bbff"

    @patch(_LIST_CALENDARS)
    def test_calendar_id_not_found_returns_defaults(
        self, mock_list_calendars: MagicMock
    ) -> None:
        mock_list_calendars.return_value = {
            "items": [
                {
                    "id": "other-cal",
                    "summary": "Other",
                    "backgroundColor": "#aabbcc",
                },
            ]
        }
        name, color = fetch_calendar_color("cal-123", "user-1")
        assert name == "Calendar"
        assert color == "#00bbff"

    @patch(_LIST_CALENDARS)
    def test_missing_summary_field_uses_default(
        self, mock_list_calendars: MagicMock
    ) -> None:
        mock_list_calendars.return_value = {
            "items": [
                {
                    "id": "cal-123",
                    "backgroundColor": "#ff0000",
                },
            ]
        }
        name, color = fetch_calendar_color("cal-123", "user-1")
        assert name == "Calendar"
        assert color == "#ff0000"

    @patch(_LIST_CALENDARS)
    def test_missing_background_color_uses_default(
        self, mock_list_calendars: MagicMock
    ) -> None:
        mock_list_calendars.return_value = {
            "items": [
                {
                    "id": "cal-123",
                    "summary": "Personal",
                },
            ]
        }
        name, color = fetch_calendar_color("cal-123", "user-1")
        assert name == "Personal"
        assert color == "#00bbff"

    @patch(_LIST_CALENDARS)
    def test_missing_both_fields_uses_defaults(
        self, mock_list_calendars: MagicMock
    ) -> None:
        mock_list_calendars.return_value = {
            "items": [
                {
                    "id": "cal-123",
                },
            ]
        }
        name, color = fetch_calendar_color("cal-123", "user-1")
        assert name == "Calendar"
        assert color == "#00bbff"

    @patch(_LIST_CALENDARS)
    def test_non_dict_response_returns_defaults(
        self, mock_list_calendars: MagicMock
    ) -> None:
        mock_list_calendars.return_value = [{"id": "cal-123"}]
        name, color = fetch_calendar_color("cal-123", "user-1")
        assert name == "Calendar"
        assert color == "#00bbff"

    @patch(_LIST_CALENDARS)
    def test_exception_returns_defaults(self, mock_list_calendars: MagicMock) -> None:
        mock_list_calendars.side_effect = RuntimeError("connection failed")
        name, color = fetch_calendar_color("cal-123", "user-1")
        assert name == "Calendar"
        assert color == "#00bbff"

    @patch(_LIST_CALENDARS)
    def test_none_response_returns_defaults(
        self, mock_list_calendars: MagicMock
    ) -> None:
        mock_list_calendars.return_value = None
        name, color = fetch_calendar_color("cal-123", "user-1")
        assert name == "Calendar"
        assert color == "#00bbff"

    @patch(_LIST_CALENDARS)
    def test_multiple_calendars_matches_correct_one(
        self, mock_list_calendars: MagicMock
    ) -> None:
        mock_list_calendars.return_value = {
            "items": [
                {
                    "id": "cal-aaa",
                    "summary": "First",
                    "backgroundColor": "#111111",
                },
                {
                    "id": "cal-bbb",
                    "summary": "Second",
                    "backgroundColor": "#222222",
                },
                {
                    "id": "cal-ccc",
                    "summary": "Third",
                    "backgroundColor": "#333333",
                },
            ]
        }
        name, color = fetch_calendar_color("cal-bbb", "user-1")
        assert name == "Second"
        assert color == "#222222"


# ---------------------------------------------------------------------------
# extract_event_dates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractEventDates:
    def test_datetime_format_with_T(self) -> None:
        options: List[Dict[str, Any]] = [
            {"start": "2025-01-15T10:00:00Z"},
            {"start": "2025-01-16T14:30:00-05:00"},
        ]
        result = extract_event_dates(options)
        assert result == {"2025-01-15", "2025-01-16"}

    def test_date_format_without_T(self) -> None:
        options: List[Dict[str, Any]] = [
            {"start": "2025-03-01"},
            {"start": "2025-03-02"},
        ]
        result = extract_event_dates(options)
        assert result == {"2025-03-01", "2025-03-02"}

    def test_empty_list(self) -> None:
        result = extract_event_dates([])
        assert result == set()

    def test_mixed_formats(self) -> None:
        options: List[Dict[str, Any]] = [
            {"start": "2025-01-15T10:00:00Z"},
            {"start": "2025-01-16"},
        ]
        result = extract_event_dates(options)
        assert result == {"2025-01-15", "2025-01-16"}

    def test_duplicate_dates_deduplicated(self) -> None:
        options: List[Dict[str, Any]] = [
            {"start": "2025-01-15T09:00:00Z"},
            {"start": "2025-01-15T14:00:00Z"},
        ]
        result = extract_event_dates(options)
        assert result == {"2025-01-15"}

    def test_missing_start_key(self) -> None:
        options: List[Dict[str, Any]] = [
            {"end": "2025-01-15T10:00:00Z"},
        ]
        result = extract_event_dates(options)
        assert result == set()

    def test_empty_start_value(self) -> None:
        options: List[Dict[str, Any]] = [
            {"start": ""},
        ]
        result = extract_event_dates(options)
        assert result == set()

    @pytest.mark.parametrize(
        "start_value,expected_date",
        [
            ("2025-06-01T00:00:00Z", "2025-06-01"),
            ("2025-06-01T23:59:59+05:30", "2025-06-01"),
            ("2025-06-01", "2025-06-01"),
            ("2025-12-25T12:00:00", "2025-12-25"),
        ],
        ids=[
            "datetime-utc",
            "datetime-offset",
            "date-only",
            "datetime-no-tz",
        ],
    )
    def test_parametrized_start_formats(
        self, start_value: str, expected_date: str
    ) -> None:
        result = extract_event_dates([{"start": start_value}])
        assert result == {expected_date}

    def test_single_event(self) -> None:
        options: List[Dict[str, Any]] = [
            {"start": "2025-07-04T09:00:00Z"},
        ]
        result = extract_event_dates(options)
        assert result == {"2025-07-04"}


# ---------------------------------------------------------------------------
# fetch_same_day_events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchSameDayEvents:
    @patch(_GET_CALENDAR_EVENTS)
    def test_success_single_date(self, mock_get_events: MagicMock) -> None:
        mock_get_events.return_value = {
            "events": [
                {"id": "evt-1", "summary": "Meeting"},
                {"id": "evt-2", "summary": "Lunch"},
            ]
        }
        result = fetch_same_day_events({"2025-01-15"}, "token-abc", "user-1")
        assert len(result) == 2
        assert result[0]["id"] == "evt-1"
        assert result[1]["id"] == "evt-2"
        mock_get_events.assert_called_once_with(
            access_token="token-abc",
            user_id="user-1",
            time_min="2025-01-15T00:00:00Z",
            time_max="2025-01-15T23:59:59Z",
        )

    @patch(_GET_CALENDAR_EVENTS)
    def test_success_multiple_dates(self, mock_get_events: MagicMock) -> None:
        def side_effect(**kwargs: Any) -> Dict[str, Any]:
            if "2025-01-15" in kwargs["time_min"]:
                return {"events": [{"id": "evt-1"}]}
            if "2025-01-16" in kwargs["time_min"]:
                return {"events": [{"id": "evt-2"}, {"id": "evt-3"}]}
            return {"events": []}

        mock_get_events.side_effect = side_effect
        result = fetch_same_day_events(
            {"2025-01-15", "2025-01-16"}, "token-abc", "user-1"
        )
        assert len(result) == 3
        event_ids = {e["id"] for e in result}
        assert event_ids == {"evt-1", "evt-2", "evt-3"}

    @patch(_GET_CALENDAR_EVENTS)
    def test_empty_events_key(self, mock_get_events: MagicMock) -> None:
        mock_get_events.return_value = {"events": []}
        result = fetch_same_day_events({"2025-01-15"}, "token-abc", "user-1")
        assert result == []

    @patch(_GET_CALENDAR_EVENTS)
    def test_none_response_no_events(self, mock_get_events: MagicMock) -> None:
        mock_get_events.return_value = None
        result = fetch_same_day_events({"2025-01-15"}, "token-abc", "user-1")
        assert result == []

    @patch(_GET_CALENDAR_EVENTS)
    def test_partial_failure_continues(self, mock_get_events: MagicMock) -> None:
        """When one date fetch fails, events for other dates are still returned."""
        call_count = 0

        def side_effect(**kwargs: Any) -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("API timeout")
            return {"events": [{"id": "evt-ok"}]}

        mock_get_events.side_effect = side_effect
        result = fetch_same_day_events(
            {"2025-01-15", "2025-01-16"}, "token-abc", "user-1"
        )
        # One date failed, one succeeded
        assert len(result) == 1
        assert result[0]["id"] == "evt-ok"

    @patch(_GET_CALENDAR_EVENTS)
    def test_all_dates_fail_returns_empty(self, mock_get_events: MagicMock) -> None:
        mock_get_events.side_effect = RuntimeError("total failure")
        result = fetch_same_day_events(
            {"2025-01-15", "2025-01-16"}, "token-abc", "user-1"
        )
        assert result == []

    def test_empty_dates_set(self) -> None:
        result = fetch_same_day_events(set(), "token-abc", "user-1")
        assert result == []

    @patch(_GET_CALENDAR_EVENTS)
    def test_response_missing_events_key(self, mock_get_events: MagicMock) -> None:
        mock_get_events.return_value = {"other_key": "value"}
        result = fetch_same_day_events({"2025-01-15"}, "token-abc", "user-1")
        assert result == []

    @patch(_GET_CALENDAR_EVENTS)
    def test_time_min_and_max_format(self, mock_get_events: MagicMock) -> None:
        """Verify that the time boundaries are correctly formatted."""
        mock_get_events.return_value = {"events": []}
        fetch_same_day_events({"2025-12-31"}, "token-abc", "user-1")
        mock_get_events.assert_called_once_with(
            access_token="token-abc",
            user_id="user-1",
            time_min="2025-12-31T00:00:00Z",
            time_max="2025-12-31T23:59:59Z",
        )
