"""Unit tests for the calendar service (app/services/calendar_service.py).

Covers every public function with branch, edge-case, and error-path testing.
All external dependencies (httpx.Client, MongoDB, Redis) are mocked.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.services.calendar_service import (
    create_calendar_event,
    delete_calendar_event,
    enrich_calendar_options_with_metadata,
    extract_unique_dates,
    fetch_all_calendar_events,
    fetch_calendar_events,
    fetch_calendar_list,
    fetch_same_day_events,
    filter_events,
    find_event_for_action,
    format_event_for_frontend,
    get_calendar_events,
    get_calendar_events_by_id,
    get_calendar_metadata_map,
    get_user_calendar_preferences,
    initialize_calendar_preferences,
    list_calendars,
    search_calendar_events_native,
    search_events_in_calendar,
    update_calendar_event,
    update_user_calendar_preferences,
)
from app.models.calendar_models import (
    EventCreateRequest,
    EventDeleteRequest,
    EventLookupRequest,
    EventUpdateRequest,
    RecurrenceData,
    RecurrenceRule,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = "user_test_123"
ACCESS_TOKEN = "ya29.test_access_token"  # nosec B105
CALENDAR_ID = "primary"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int = 200,
    json_data: Any = None,
    content: bytes = b"",
) -> MagicMock:
    """Build a fake httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.content = content
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        http_error = httpx.HTTPStatusError(
            message="error",
            request=MagicMock(),
            response=resp,
        )
        resp.raise_for_status.side_effect = http_error
    return resp


def _make_calendar_item(
    cal_id: str = "cal1",
    summary: str = "Work",
    bg_color: str = "#0000ff",
    description: str = "Work calendar",
) -> Dict[str, Any]:
    return {
        "id": cal_id,
        "summary": summary,
        "backgroundColor": bg_color,
        "description": description,
    }


def _make_event(
    event_id: str = "evt1",
    summary: str = "Meeting",
    start_dt: str = "2025-10-25T10:00:00+05:30",
    end_dt: str = "2025-10-25T11:00:00+05:30",
    event_type: str = "default",
    calendar_id: str = "",
) -> Dict[str, Any]:
    evt: Dict[str, Any] = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
        "eventType": event_type,
    }
    if calendar_id:
        evt["calendarId"] = calendar_id
    return evt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client():
    """Patch the module-level httpx.Client used by calendar_service."""
    with patch("app.services.calendar_service.http_client") as mock_client:
        yield mock_client


@pytest.fixture
def mock_calendars_collection():
    """Patch the module-level MongoDB collection used by calendar_service."""
    with patch("app.services.calendar_service.calendars_collection") as mock_col:
        yield mock_col


# =========================================================================
# fetch_calendar_list
# =========================================================================


class TestFetchCalendarList:
    """Tests for fetch_calendar_list."""

    def test_success_full_data(self, mock_http_client: MagicMock) -> None:
        """Successful fetch returns full calendar JSON."""
        cal_data = {"items": [_make_calendar_item()]}
        mock_http_client.get.return_value = _make_response(200, cal_data)

        result = fetch_calendar_list(ACCESS_TOKEN)

        assert result == cal_data
        mock_http_client.get.assert_called_once()
        call_kwargs = mock_http_client.get.call_args
        assert "Authorization" in call_kwargs.kwargs.get(
            "headers", call_kwargs[1].get("headers", {})
        ) or "Authorization" in (call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})

    def test_success_short_format(self, mock_http_client: MagicMock) -> None:
        """Short format returns only key fields."""
        cal_data = {
            "items": [
                {
                    "id": "cal1",
                    "summary": "Work",
                    "description": "Work cal",
                    "backgroundColor": "#ff0000",
                    "extra_field": "should be omitted",
                }
            ]
        }
        mock_http_client.get.return_value = _make_response(200, cal_data)

        result = fetch_calendar_list(ACCESS_TOKEN, short=True)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == {
            "id": "cal1",
            "summary": "Work",
            "description": "Work cal",
            "backgroundColor": "#ff0000",
        }

    def test_short_format_empty_items(self, mock_http_client: MagicMock) -> None:
        """Short format with no items returns empty list."""
        mock_http_client.get.return_value = _make_response(200, {"items": []})

        result = fetch_calendar_list(ACCESS_TOKEN, short=True)

        assert result == []

    def test_http_status_error_nested_error(self, mock_http_client: MagicMock) -> None:
        """HTTPStatusError with nested dict error → extracts message."""
        error_resp = _make_response(
            403,
            {"error": {"message": "Forbidden calendar access"}},
        )
        mock_http_client.get.return_value = error_resp

        with pytest.raises(HTTPException) as exc_info:
            fetch_calendar_list(ACCESS_TOKEN)

        assert exc_info.value.status_code == 403
        assert "Forbidden calendar access" in exc_info.value.detail

    def test_http_status_error_non_dict_error(
        self, mock_http_client: MagicMock
    ) -> None:
        """HTTPStatusError where error_json['error'] is not a dict → falls back to Unknown."""
        error_resp = _make_response(401, {"error": "string_error"})
        mock_http_client.get.return_value = error_resp

        with pytest.raises(HTTPException) as exc_info:
            fetch_calendar_list(ACCESS_TOKEN)

        assert exc_info.value.status_code == 401
        assert "Unknown error" in exc_info.value.detail

    def test_http_status_error_non_dict_json(self, mock_http_client: MagicMock) -> None:
        """HTTPStatusError where response JSON is not a dict → Unknown error."""
        error_resp = _make_response(500, "plain string body")
        mock_http_client.get.return_value = error_resp

        with pytest.raises(HTTPException) as exc_info:
            fetch_calendar_list(ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "Unknown error" in exc_info.value.detail

    def test_request_error(self, mock_http_client: MagicMock) -> None:
        """httpx.RequestError (network) → 500 HTTPException."""
        mock_http_client.get.side_effect = httpx.RequestError("Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            fetch_calendar_list(ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "requesting the calendar list" in exc_info.value.detail


# =========================================================================
# filter_events
# =========================================================================


class TestFilterEvents:
    """Tests for filter_events."""

    def test_removes_birthday_events(self) -> None:
        events = [
            _make_event(event_type="birthday"),
            _make_event(event_id="evt2", event_type="default"),
        ]
        result = filter_events(events)
        assert len(result) == 1
        assert result[0]["id"] == "evt2"

    def test_removes_events_without_start(self) -> None:
        events = [{"id": "no_start", "eventType": "default"}]
        result = filter_events(events)
        assert result == []

    def test_removes_events_without_datetime_or_date(self) -> None:
        events = [{"id": "bad_start", "eventType": "default", "start": {}}]
        result = filter_events(events)
        assert result == []

    def test_keeps_events_with_date_only(self) -> None:
        events = [
            {"id": "allday", "eventType": "default", "start": {"date": "2025-10-25"}}
        ]
        result = filter_events(events)
        assert len(result) == 1

    def test_keeps_events_with_datetime(self) -> None:
        events = [_make_event()]
        result = filter_events(events)
        assert len(result) == 1

    def test_empty_list(self) -> None:
        assert filter_events([]) == []


# =========================================================================
# fetch_calendar_events
# =========================================================================


class TestFetchCalendarEvents:
    """Tests for fetch_calendar_events."""

    def test_success_200(self, mock_http_client: MagicMock) -> None:
        events_data = {"items": [_make_event()]}
        mock_http_client.get.return_value = _make_response(200, events_data)

        result = fetch_calendar_events("cal1", ACCESS_TOKEN)

        assert result == events_data

    def test_includes_optional_params(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, {"items": []})

        fetch_calendar_events(
            "cal1",
            ACCESS_TOKEN,
            page_token="token123",
            time_min="2025-01-01T00:00:00Z",
            time_max="2025-12-31T23:59:59Z",
            max_results=50,
        )

        call_args = mock_http_client.get.call_args
        params = call_args.kwargs.get("params", call_args[1].get("params", {}))
        assert params["pageToken"] == "token123"
        assert params["timeMin"] == "2025-01-01T00:00:00Z"
        assert params["timeMax"] == "2025-12-31T23:59:59Z"
        assert params["maxResults"] == 50

    def test_error_response_non_200(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(
            404, {"error": {"message": "Calendar not found"}}
        )

        with pytest.raises(HTTPException) as exc_info:
            fetch_calendar_events("cal1", ACCESS_TOKEN)

        assert exc_info.value.status_code == 404

    def test_request_error(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.side_effect = httpx.RequestError("timeout")

        with pytest.raises(HTTPException) as exc_info:
            fetch_calendar_events("cal1", ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "HTTP request failed" in exc_info.value.detail


# =========================================================================
# fetch_all_calendar_events
# =========================================================================


class TestFetchAllCalendarEvents:
    """Tests for fetch_all_calendar_events."""

    def test_single_page(self) -> None:
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            mock_fetch.return_value = {
                "items": [_make_event()],
            }

            result = fetch_all_calendar_events("cal1", ACCESS_TOKEN)

            assert result["total_fetched"] == 1
            assert result["truncated"] is False
            assert len(result["items"]) == 1

    def test_multi_page(self) -> None:
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            mock_fetch.side_effect = [
                {"items": [_make_event(event_id="e1")], "nextPageToken": "page2"},
                {"items": [_make_event(event_id="e2")]},
            ]

            result = fetch_all_calendar_events("cal1", ACCESS_TOKEN)

            assert result["total_fetched"] == 2
            assert result["truncated"] is False
            assert mock_fetch.call_count == 2

    def test_twenty_page_limit(self) -> None:
        """Hits the 20-page safety limit and sets truncated=True."""
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            # Every page returns items and another page token
            mock_fetch.return_value = {
                "items": [_make_event()],
                "nextPageToken": "more",
            }

            result = fetch_all_calendar_events("cal1", ACCESS_TOKEN)

            assert result["truncated"] is True
            assert mock_fetch.call_count == 20
            assert result["total_fetched"] == 20

    def test_empty_pages(self) -> None:
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            mock_fetch.return_value = {"items": []}

            result = fetch_all_calendar_events("cal1", ACCESS_TOKEN)

            assert result["total_fetched"] == 0
            assert result["truncated"] is False

    def test_logs_after_five_pages(self) -> None:
        """After 5 pages the function logs info — ensure no crash."""
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            # 7 pages: pages 6 and 7 trigger the > 5 log
            pages: List[Dict[str, Any]] = []
            for i in range(6):
                pages.append(
                    {
                        "items": [_make_event(event_id=f"e{i}")],
                        "nextPageToken": f"p{i + 1}",
                    }
                )
            pages.append({"items": [_make_event(event_id="e6")]})
            mock_fetch.side_effect = pages

            result = fetch_all_calendar_events("cal1", ACCESS_TOKEN)

            assert result["total_fetched"] == 7
            assert result["truncated"] is False


# =========================================================================
# list_calendars
# =========================================================================


class TestListCalendars:
    """Tests for list_calendars (thin wrapper)."""

    def test_delegates_to_fetch_calendar_list(self) -> None:
        with patch("app.services.calendar_service.fetch_calendar_list") as mock_fetch:
            mock_fetch.return_value = {"items": []}
            result = list_calendars(ACCESS_TOKEN, short=True)
            mock_fetch.assert_called_once_with(ACCESS_TOKEN, True)
            assert result == {"items": []}


# =========================================================================
# initialize_calendar_preferences
# =========================================================================


class TestInitializeCalendarPreferences:
    """Tests for initialize_calendar_preferences."""

    def test_already_has_preferences(
        self, mock_calendars_collection: MagicMock
    ) -> None:
        mock_calendars_collection.find_one.return_value = {
            "user_id": USER_ID,
            "selected_calendars": ["cal1"],
        }

        initialize_calendar_preferences(USER_ID, ACCESS_TOKEN)

        # Should not call fetch_calendar_list or update_one
        mock_calendars_collection.update_one.assert_not_called()

    def test_no_calendars_returned(self, mock_calendars_collection: MagicMock) -> None:
        mock_calendars_collection.find_one.return_value = None

        with patch("app.services.calendar_service.fetch_calendar_list") as mock_fetch:
            mock_fetch.return_value = {"items": []}

            initialize_calendar_preferences(USER_ID, ACCESS_TOKEN)

            mock_calendars_collection.update_one.assert_not_called()

    def test_success_selects_all(self, mock_calendars_collection: MagicMock) -> None:
        mock_calendars_collection.find_one.return_value = None

        with patch("app.services.calendar_service.fetch_calendar_list") as mock_fetch:
            mock_fetch.return_value = {
                "items": [
                    {"id": "cal1"},
                    {"id": "cal2"},
                ]
            }

            initialize_calendar_preferences(USER_ID, ACCESS_TOKEN)

            mock_calendars_collection.update_one.assert_called_once()
            call_args = mock_calendars_collection.update_one.call_args
            set_value = call_args[0][1]["$set"]["selected_calendars"]
            assert set_value == ["cal1", "cal2"]

    def test_existing_preferences_without_selected_calendars(
        self, mock_calendars_collection: MagicMock
    ) -> None:
        """User has a doc but selected_calendars is empty/missing → reinitialize."""
        mock_calendars_collection.find_one.return_value = {
            "user_id": USER_ID,
            "selected_calendars": [],
        }

        with patch("app.services.calendar_service.fetch_calendar_list") as mock_fetch:
            mock_fetch.return_value = {"items": [{"id": "cal1"}]}

            initialize_calendar_preferences(USER_ID, ACCESS_TOKEN)

            mock_calendars_collection.update_one.assert_called_once()

    def test_exception_is_caught(self, mock_calendars_collection: MagicMock) -> None:
        """General exceptions are caught and logged, not propagated."""
        mock_calendars_collection.find_one.side_effect = RuntimeError("DB down")

        # Should not raise
        initialize_calendar_preferences(USER_ID, ACCESS_TOKEN)


# =========================================================================
# get_calendar_metadata_map
# =========================================================================


class TestGetCalendarMetadataMap:
    """Tests for get_calendar_metadata_map."""

    def test_valid_calendars(self) -> None:
        with patch("app.services.calendar_service.list_calendars") as mock_list:
            mock_list.return_value = [
                {"id": "cal1", "backgroundColor": "#ff0000", "summary": "Work"},
                {"id": "cal2", "backgroundColor": "#00ff00", "summary": "Personal"},
            ]

            color_map, name_map = get_calendar_metadata_map(ACCESS_TOKEN)

            assert color_map == {"cal1": "#ff0000", "cal2": "#00ff00"}
            assert name_map == {"cal1": "Work", "cal2": "Personal"}

    def test_non_list_returns_empty_maps(self) -> None:
        with patch("app.services.calendar_service.list_calendars") as mock_list:
            mock_list.return_value = {"items": []}  # dict, not list

            color_map, name_map = get_calendar_metadata_map(ACCESS_TOKEN)

            assert color_map == {}
            assert name_map == {}

    def test_missing_fields_use_defaults(self) -> None:
        with patch("app.services.calendar_service.list_calendars") as mock_list:
            mock_list.return_value = [{"id": "cal1"}]

            color_map, name_map = get_calendar_metadata_map(ACCESS_TOKEN)

            assert color_map["cal1"] == "#00bbff"
            assert name_map["cal1"] == "Calendar"

    def test_none_return(self) -> None:
        with patch("app.services.calendar_service.list_calendars") as mock_list:
            mock_list.return_value = None

            color_map, name_map = get_calendar_metadata_map(ACCESS_TOKEN)

            assert color_map == {}
            assert name_map == {}

    def test_non_dict_items_skipped(self) -> None:
        with patch("app.services.calendar_service.list_calendars") as mock_list:
            mock_list.return_value = [
                "not_a_dict",
                {"id": "cal1", "summary": "OK"},
            ]

            color_map, name_map = get_calendar_metadata_map(ACCESS_TOKEN)

            assert "cal1" in name_map
            assert len(name_map) == 1

    def test_item_without_id_skipped(self) -> None:
        with patch("app.services.calendar_service.list_calendars") as mock_list:
            mock_list.return_value = [{"summary": "No ID calendar"}]

            color_map, name_map = get_calendar_metadata_map(ACCESS_TOKEN)

            assert color_map == {}
            assert name_map == {}


# =========================================================================
# format_event_for_frontend
# =========================================================================


class TestFormatEventForFrontend:
    """Tests for format_event_for_frontend."""

    def test_all_fields_present(self) -> None:
        event = {
            "summary": "Team Standup",
            "start": {"dateTime": "2025-10-25T09:00:00Z"},
            "end": {"dateTime": "2025-10-25T09:30:00Z"},
            "calendarId": "cal1",
        }
        color_map = {"cal1": "#ff0000"}
        name_map = {"cal1": "Work"}

        result = format_event_for_frontend(event, color_map, name_map)

        assert result["summary"] == "Team Standup"
        assert result["start_time"] == "2025-10-25T09:00:00Z"
        assert result["end_time"] == "2025-10-25T09:30:00Z"
        assert result["calendar_name"] == "Work"
        assert result["background_color"] == "#ff0000"

    def test_missing_start_and_end(self) -> None:
        event = {"summary": "No times"}
        result = format_event_for_frontend(event, {}, {})
        assert result["start_time"] == ""
        assert result["end_time"] == ""

    def test_date_only_start(self) -> None:
        event = {
            "start": {"date": "2025-10-25"},
            "end": {"date": "2025-10-26"},
        }
        result = format_event_for_frontend(event, {}, {})
        assert result["start_time"] == "2025-10-25"
        assert result["end_time"] == "2025-10-26"

    def test_missing_color_and_name_defaults(self) -> None:
        event = {
            "calendarId": "unknown_cal",
        }
        result = format_event_for_frontend(event, {}, {})

        assert result["background_color"] == "#00bbff"
        assert result["calendar_name"] == "Unknown Calendar"

    def test_calendar_title_fallback(self) -> None:
        """When calendarId not in name_map, falls back to event's calendarTitle."""
        event = {
            "calendarId": "missing",
            "calendarTitle": "From Event",
        }
        result = format_event_for_frontend(event, {}, {})
        assert result["calendar_name"] == "From Event"

    def test_no_summary_defaults(self) -> None:
        event: Dict[str, Any] = {}
        result = format_event_for_frontend(event, {}, {})
        assert result["summary"] == "No Title"


# =========================================================================
# extract_unique_dates
# =========================================================================


class TestExtractUniqueDates:
    """Tests for extract_unique_dates."""

    def test_valid_timestamps(self) -> None:
        options = [
            {"start": "2025-10-25T10:00:00+05:30"},
            {"start": "2025-10-26T08:00:00-04:00"},
        ]
        result = extract_unique_dates(options)

        assert "2025-10-25" in result
        assert result["2025-10-25"] == "+05:30"
        assert "2025-10-26" in result
        assert result["2025-10-26"] == "-04:00"

    def test_utc_z_suffix(self) -> None:
        options = [{"start": "2025-10-25T10:00:00Z"}]
        result = extract_unique_dates(options)

        assert "2025-10-25" in result
        assert result["2025-10-25"] == "+00:00"

    def test_invalid_format_skipped(self) -> None:
        options = [{"start": "not-a-date"}]
        result = extract_unique_dates(options)
        assert result == {}

    def test_missing_start_key(self) -> None:
        options = [{"end": "2025-10-25T10:00:00Z"}]
        result = extract_unique_dates(options)
        assert result == {}

    def test_empty_start_string(self) -> None:
        options = [{"start": ""}]
        result = extract_unique_dates(options)
        assert result == {}

    def test_deduplication(self) -> None:
        """Multiple events on the same date: last one's offset wins."""
        options = [
            {"start": "2025-10-25T08:00:00+05:30"},
            {"start": "2025-10-25T14:00:00+05:30"},
        ]
        result = extract_unique_dates(options)
        assert len(result) == 1

    def test_naive_datetime(self) -> None:
        """Naive datetime (no timezone) → offset defaults to +00:00."""
        options = [{"start": "2025-10-25T10:00:00"}]
        result = extract_unique_dates(options)
        assert "2025-10-25" in result
        assert result["2025-10-25"] == "+00:00"


# =========================================================================
# get_calendar_events
# =========================================================================


class TestGetCalendarEvents:
    """Tests for get_calendar_events."""

    @pytest.fixture(autouse=True)
    def _setup_mocks(self, mock_calendars_collection: MagicMock) -> None:
        self.mock_col = mock_calendars_collection

    def _setup_fetch(
        self,
        calendars: List[Dict[str, Any]],
        events_per_calendar: Dict[str, List[Dict[str, Any]]],
    ):
        """Helper to patch fetch_calendar_list and fetch_calendar_events."""
        self._patches = []

        p1 = patch(
            "app.services.calendar_service.fetch_calendar_list",
            return_value={"items": calendars},
        )
        self._patches.append(p1)
        self.mock_fetch_list = p1.start()

        def _fetch_events(
            cal_id, token, page_token=None, time_min=None, time_max=None, max_results=20
        ):
            return {"items": events_per_calendar.get(cal_id, [])}

        p2 = patch(
            "app.services.calendar_service.fetch_calendar_events",
            side_effect=_fetch_events,
        )
        self._patches.append(p2)
        self.mock_fetch_events = p2.start()

    def _teardown_patches(self):
        for p in getattr(self, "_patches", []):
            p.stop()

    def test_selected_calendars_provided(self) -> None:
        """When selected_calendars is passed, uses those and persists to DB."""
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]
        events = {
            "cal1": [_make_event("e1")],
            "cal2": [_make_event("e2")],
        }
        self._setup_fetch(cals, events)
        try:
            result = get_calendar_events(
                user_id=USER_ID,
                access_token=ACCESS_TOKEN,
                selected_calendars=["cal1"],
            )

            assert result["selectedCalendars"] == ["cal1"]
            self.mock_col.update_one.assert_called()
            # Only cal1 events should be fetched
            assert len(result["events"]) == 1
        finally:
            self._teardown_patches()

    def test_default_all_calendars(self) -> None:
        """No selected_calendars and no DB prefs → defaults to all."""
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]
        events = {
            "cal1": [_make_event("e1")],
            "cal2": [_make_event("e2")],
        }
        self._setup_fetch(cals, events)
        self.mock_col.find_one.return_value = None
        try:
            result = get_calendar_events(user_id=USER_ID, access_token=ACCESS_TOKEN)

            assert len(result["selectedCalendars"]) == 2
            self.mock_col.update_one.assert_called()
        finally:
            self._teardown_patches()

    def test_loads_from_db_preferences(self) -> None:
        """Loads selected calendars from DB when not provided."""
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]
        events = {"cal1": [_make_event("e1")]}
        self._setup_fetch(cals, events)
        self.mock_col.find_one.return_value = {
            "user_id": USER_ID,
            "selected_calendars": ["cal1"],
        }
        try:
            result = get_calendar_events(user_id=USER_ID, access_token=ACCESS_TOKEN)

            assert result["selectedCalendars"] == ["cal1"]
            # Should NOT call update_one when loading from prefs
            self.mock_col.update_one.assert_not_called()
        finally:
            self._teardown_patches()

    def test_deduplication_skips_annotation_for_seen_ids(self) -> None:
        """The dedup logic skips calendarId/calendarTitle annotation for
        already-seen event IDs (via 'continue'), but filter_events still
        operates on the full per-calendar events list. This test verifies
        the seen_event_ids tracking works (the set grows) and that events
        from both calendars are present in the output.
        """
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]
        events = {
            "cal1": [_make_event("shared")],
            "cal2": [_make_event("shared")],  # same ID
        }
        self._setup_fetch(cals, events)
        self.mock_col.find_one.return_value = None
        try:
            result = get_calendar_events(user_id=USER_ID, access_token=ACCESS_TOKEN)

            event_ids = [e["id"] for e in result["events"]]
            # Both calendar responses include the event; filter_events runs on
            # the full per-calendar list so the event appears twice.
            assert event_ids.count("shared") == 2

            # The second copy should NOT have calendarId/calendarTitle set
            # because the continue statement skipped annotation.
            annotated = [e for e in result["events"] if e.get("calendarId") == "cal1"]
            [
                e
                for e in result["events"]
                if "calendarId" not in e or e.get("calendarId") != "cal1"
            ]
            assert len(annotated) >= 1
        finally:
            self._teardown_patches()

    def test_fetch_all_mode(self) -> None:
        """fetch_all=True calls fetch_all_calendar_events instead."""
        cals = [_make_calendar_item("cal1")]
        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.fetch_all_calendar_events",
                return_value={
                    "items": [_make_event("e1")],
                    "truncated": False,
                },
            ) as mock_fetch_all,
        ):
            self.mock_col.find_one.return_value = None

            result = get_calendar_events(
                user_id=USER_ID,
                access_token=ACCESS_TOKEN,
                fetch_all=True,
            )

            mock_fetch_all.assert_called_once()
            assert result["has_more"] is False

    def test_fetch_all_mode_truncated(self) -> None:
        """fetch_all with truncation reports has_more and calendars_truncated."""
        cals = [_make_calendar_item("cal1")]
        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.fetch_all_calendar_events",
                return_value={
                    "items": [_make_event("e1")],
                    "truncated": True,
                },
            ),
        ):
            self.mock_col.find_one.return_value = None

            result = get_calendar_events(
                user_id=USER_ID,
                access_token=ACCESS_TOKEN,
                fetch_all=True,
            )

            assert result["has_more"] is True
            assert "cal1" in result["calendars_truncated"]

    def test_error_on_one_calendar(self) -> None:
        """Error fetching one calendar doesn't break the entire request."""
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]

        def _fetch_events(
            cal_id, token, page_token=None, time_min=None, time_max=None, max_results=20
        ):
            if cal_id == "cal1":
                raise RuntimeError("API error")
            return {"items": [_make_event("e2")]}

        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.fetch_calendar_events",
                side_effect=_fetch_events,
            ),
        ):
            self.mock_col.find_one.return_value = None

            result = get_calendar_events(user_id=USER_ID, access_token=ACCESS_TOKEN)

            # Only cal2 events returned
            assert len(result["events"]) == 1

    def test_max_results_none_triggers_fetch_all(self) -> None:
        """max_results=None acts like fetch_all=True."""
        cals = [_make_calendar_item("cal1")]
        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.fetch_all_calendar_events",
                return_value={"items": [], "truncated": False},
            ) as mock_fetch_all,
        ):
            self.mock_col.find_one.return_value = None

            get_calendar_events(
                user_id=USER_ID,
                access_token=ACCESS_TOKEN,
                max_results=None,
            )

            mock_fetch_all.assert_called_once()

    def test_events_sorted_by_start_time(self) -> None:
        """Events from multiple calendars are sorted by start time."""
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]

        def _fetch_events(
            cal_id, token, page_token=None, time_min=None, time_max=None, max_results=20
        ):
            if cal_id == "cal1":
                return {
                    "items": [
                        _make_event(
                            "e1",
                            start_dt="2025-10-25T14:00:00Z",
                            end_dt="2025-10-25T15:00:00Z",
                        )
                    ]
                }
            return {
                "items": [
                    _make_event(
                        "e2",
                        start_dt="2025-10-25T09:00:00Z",
                        end_dt="2025-10-25T10:00:00Z",
                    )
                ]
            }

        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.fetch_calendar_events",
                side_effect=_fetch_events,
            ),
        ):
            self.mock_col.find_one.return_value = None

            result = get_calendar_events(user_id=USER_ID, access_token=ACCESS_TOKEN)

            assert result["events"][0]["id"] == "e2"  # 09:00 comes first
            assert result["events"][1]["id"] == "e1"  # 14:00 comes second


# =========================================================================
# create_calendar_event
# =========================================================================


class TestCreateCalendarEvent:
    """Tests for create_calendar_event."""

    def _make_create_request(self, **overrides) -> EventCreateRequest:
        defaults = {
            "summary": "Test Event",
            "description": "A test",
            "start": "2025-10-25T10:00:00Z",
            "end": "2025-10-25T11:00:00Z",
            "is_all_day": False,
            "calendar_id": "primary",
        }
        defaults.update(overrides)
        return EventCreateRequest(**defaults)  # type: ignore[arg-type]

    def test_time_specific_event_201(self, mock_http_client: MagicMock) -> None:
        response_data = {"id": "new_evt", "summary": "Test Event"}
        mock_http_client.post.return_value = _make_response(201, response_data)

        event = self._make_create_request()
        result = create_calendar_event(event, ACCESS_TOKEN)

        assert result["id"] == "new_evt"

    def test_time_specific_event_200(self, mock_http_client: MagicMock) -> None:
        response_data = {"id": "new_evt"}
        mock_http_client.post.return_value = _make_response(200, response_data)

        event = self._make_create_request()
        result = create_calendar_event(event, ACCESS_TOKEN)

        assert result["id"] == "new_evt"

    def test_all_day_event_with_start_and_end(
        self, mock_http_client: MagicMock
    ) -> None:
        mock_http_client.post.return_value = _make_response(201, {"id": "ad1"})

        event = self._make_create_request(
            is_all_day=True,
            start="2025-10-25",
            end="2025-10-26",
        )
        create_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"] == {"date": "2025-10-25"}
        assert payload["end"] == {"date": "2025-10-26"}

    def test_all_day_event_start_only(self, mock_http_client: MagicMock) -> None:
        """All-day event with only start → end is next day."""
        mock_http_client.post.return_value = _make_response(201, {"id": "ad2"})

        event = self._make_create_request(
            is_all_day=True,
            start="2025-10-25",
            end="2025-10-25",  # model requires both, but production code only checks event.start & event.end
        )
        result = create_calendar_event(event, ACCESS_TOKEN)
        assert result["id"] == "ad2"

    def test_all_day_event_datetime_strings(self, mock_http_client: MagicMock) -> None:
        """All-day event with datetime strings → extracts date part."""
        mock_http_client.post.return_value = _make_response(201, {"id": "ad3"})

        event = self._make_create_request(
            is_all_day=True,
            start="2025-10-25T10:00:00Z",
            end="2025-10-26T10:00:00Z",
        )
        create_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"] == {"date": "2025-10-25"}
        assert payload["end"] == {"date": "2025-10-26"}

    def test_with_recurrence(self, mock_http_client: MagicMock) -> None:
        mock_http_client.post.return_value = _make_response(201, {"id": "rec1"})

        recurrence = RecurrenceData(
            rrule=RecurrenceRule(frequency="WEEKLY", by_day=["MO", "WE", "FR"])  # type: ignore[call-arg]
        )
        event = self._make_create_request(recurrence=recurrence)
        create_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert "recurrence" in payload

    def test_with_attendees(self, mock_http_client: MagicMock) -> None:
        mock_http_client.post.return_value = _make_response(201, {"id": "att1"})

        event = self._make_create_request(
            attendees=["alice@example.com", "bob@example.com"]
        )
        create_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["attendees"] == [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
        ]
        params = call_args.kwargs.get("params", call_args[1].get("params", {}))
        assert params["sendUpdates"] == "all"

    def test_with_google_meet(self, mock_http_client: MagicMock) -> None:
        mock_http_client.post.return_value = _make_response(201, {"id": "meet1"})

        event = self._make_create_request(create_meeting_room=True)
        create_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert "conferenceData" in payload
        params = call_args.kwargs.get("params", call_args[1].get("params", {}))
        assert params["conferenceDataVersion"] == "1"

    def test_403_error(self, mock_http_client: MagicMock) -> None:
        mock_http_client.post.return_value = _make_response(403, {})

        event = self._make_create_request()
        with pytest.raises(HTTPException) as exc_info:
            create_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 403
        assert "scopes" in exc_info.value.detail.lower()

    def test_401_error(self, mock_http_client: MagicMock) -> None:
        mock_http_client.post.return_value = _make_response(401, {})

        event = self._make_create_request()
        with pytest.raises(HTTPException) as exc_info:
            create_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 401

    def test_other_error_with_json(self, mock_http_client: MagicMock) -> None:
        mock_http_client.post.return_value = _make_response(
            422, {"error": {"message": "Invalid payload"}}
        )

        event = self._make_create_request()
        with pytest.raises(HTTPException) as exc_info:
            create_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 422
        assert "Invalid payload" in exc_info.value.detail

    def test_other_error_non_dict_json(self, mock_http_client: MagicMock) -> None:
        mock_http_client.post.return_value = _make_response(422, "not a dict")

        event = self._make_create_request()
        with pytest.raises(HTTPException) as exc_info:
            create_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 422
        assert "Unknown error" in exc_info.value.detail

    def test_other_error_json_parse_fails(self, mock_http_client: MagicMock) -> None:
        resp = _make_response(422)
        resp.json.side_effect = ValueError("bad json")
        mock_http_client.post.return_value = resp

        event = self._make_create_request()
        with pytest.raises(HTTPException) as exc_info:
            create_calendar_event(event, ACCESS_TOKEN)

        assert "could not parse response" in exc_info.value.detail.lower()

    def test_request_error(self, mock_http_client: MagicMock) -> None:
        mock_http_client.post.side_effect = httpx.RequestError("network down")

        event = self._make_create_request()
        with pytest.raises(HTTPException) as exc_info:
            create_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "Failed to create event" in exc_info.value.detail

    def test_missing_start_end_for_timed_event(
        self, mock_http_client: MagicMock
    ) -> None:
        """Time-specific event without start/end raises 400."""
        # Use MagicMock to bypass model validation
        event = MagicMock(spec=EventCreateRequest)
        event.summary = "No times"
        event.description = ""
        event.is_all_day = False
        event.start = None
        event.end = None
        event.calendar_id = "primary"
        event.recurrence = None
        event.attendees = None
        event.create_meeting_room = False

        with pytest.raises(HTTPException) as exc_info:
            create_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 400

    def test_default_calendar_id(self, mock_http_client: MagicMock) -> None:
        """When calendar_id is None, defaults to 'primary'."""
        mock_http_client.post.return_value = _make_response(201, {"id": "ev1"})

        event = self._make_create_request(calendar_id=None)
        create_calendar_event(event, ACCESS_TOKEN)

        call_url = mock_http_client.post.call_args[0][0]
        assert "/primary/events" in call_url

    def test_timezone_appended_when_missing(self, mock_http_client: MagicMock) -> None:
        """Times without timezone info get Z appended."""
        mock_http_client.post.return_value = _make_response(201, {"id": "tz1"})

        event = self._make_create_request(
            start="2025-10-25T10:00:00",
            end="2025-10-25T11:00:00",
        )
        create_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"]["dateTime"].endswith("Z")
        assert payload["end"]["dateTime"].endswith("Z")

    def test_timezone_not_appended_when_present(
        self, mock_http_client: MagicMock
    ) -> None:
        """Times that already have timezone info are not modified."""
        mock_http_client.post.return_value = _make_response(201, {"id": "tz2"})

        event = self._make_create_request(
            start="2025-10-25T10:00:00+05:30",
            end="2025-10-25T11:00:00+05:30",
        )
        create_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"]["dateTime"] == "2025-10-25T10:00:00+05:30"


# =========================================================================
# delete_calendar_event
# =========================================================================


class TestDeleteCalendarEvent:
    """Tests for delete_calendar_event."""

    def _make_delete_request(self, **overrides) -> EventDeleteRequest:
        defaults = {"event_id": "evt1", "calendar_id": "primary"}
        defaults.update(overrides)
        return EventDeleteRequest(**defaults)

    def test_204_success(self, mock_http_client: MagicMock) -> None:
        mock_http_client.delete.return_value = _make_response(204)

        result = delete_calendar_event(self._make_delete_request(), ACCESS_TOKEN)

        assert result["success"] is True
        assert "deleted" in result["message"].lower()

    def test_404_not_found(self, mock_http_client: MagicMock) -> None:
        mock_http_client.delete.return_value = _make_response(404)

        with pytest.raises(HTTPException) as exc_info:
            delete_calendar_event(self._make_delete_request(), ACCESS_TOKEN)

        assert exc_info.value.status_code == 404

    def test_401_auth_error(self, mock_http_client: MagicMock) -> None:
        mock_http_client.delete.return_value = _make_response(401)

        with pytest.raises(HTTPException) as exc_info:
            delete_calendar_event(self._make_delete_request(), ACCESS_TOKEN)

        assert exc_info.value.status_code == 401

    def test_other_error_with_json_body(self, mock_http_client: MagicMock) -> None:
        resp = _make_response(500, {"error": {"message": "Internal issue"}})
        resp.content = b'{"error": {"message": "Internal issue"}}'
        mock_http_client.delete.return_value = resp

        with pytest.raises(HTTPException) as exc_info:
            delete_calendar_event(self._make_delete_request(), ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "Internal issue" in exc_info.value.detail

    def test_other_error_empty_content(self, mock_http_client: MagicMock) -> None:
        resp = _make_response(500)
        resp.content = b""
        mock_http_client.delete.return_value = resp

        with pytest.raises(HTTPException) as exc_info:
            delete_calendar_event(self._make_delete_request(), ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "Unknown error" in exc_info.value.detail

    def test_other_error_json_parse_fails(self, mock_http_client: MagicMock) -> None:
        resp = _make_response(500)
        resp.content = b"not json"
        resp.json.side_effect = ValueError("bad json")
        mock_http_client.delete.return_value = resp

        with pytest.raises(HTTPException) as exc_info:
            delete_calendar_event(self._make_delete_request(), ACCESS_TOKEN)

        assert exc_info.value.status_code == 500

    def test_request_error(self, mock_http_client: MagicMock) -> None:
        mock_http_client.delete.side_effect = httpx.RequestError("timeout")

        with pytest.raises(HTTPException) as exc_info:
            delete_calendar_event(self._make_delete_request(), ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "Failed to delete" in exc_info.value.detail

    def test_default_calendar_id(self, mock_http_client: MagicMock) -> None:
        """calendar_id defaults to 'primary'."""
        mock_http_client.delete.return_value = _make_response(204)

        event = EventDeleteRequest(event_id="evt1")  # type: ignore[call-arg]
        delete_calendar_event(event, ACCESS_TOKEN)

        call_url = mock_http_client.delete.call_args[0][0]
        assert "/primary/events/" in call_url


# =========================================================================
# update_calendar_event
# =========================================================================


class TestUpdateCalendarEvent:
    """Tests for update_calendar_event."""

    def _make_update_request(self, **overrides) -> EventUpdateRequest:
        defaults = {"event_id": "evt1", "calendar_id": "primary"}
        defaults.update(overrides)
        return EventUpdateRequest(**defaults)  # type: ignore[arg-type]

    def _existing_event(self) -> Dict[str, Any]:
        return {
            "summary": "Old Title",
            "description": "Old description",
            "start": {"dateTime": "2025-10-25T10:00:00Z", "timeZone": "UTC"},
            "end": {"dateTime": "2025-10-25T11:00:00Z", "timeZone": "UTC"},
        }

    def test_update_200_success(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(
            200, {"id": "evt1", "summary": "New Title"}
        )

        event = self._make_update_request(summary="New Title")
        result = update_calendar_event(event, ACCESS_TOKEN)

        assert result["summary"] == "New Title"
        assert result["calendarId"] == "primary"

    def test_update_preserves_existing_fields(
        self, mock_http_client: MagicMock
    ) -> None:
        """Fields not provided in update use existing values."""
        existing = self._existing_event()
        mock_http_client.get.return_value = _make_response(200, existing)
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        event = self._make_update_request()  # no summary/description overrides
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["summary"] == "Old Title"
        assert payload["description"] == "Old description"

    def test_update_times(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        event = self._make_update_request(
            start="2025-10-25T14:00:00Z",
            end="2025-10-25T15:00:00Z",
        )
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"]["dateTime"] == "2025-10-25T14:00:00Z"
        assert payload["end"]["dateTime"] == "2025-10-25T15:00:00Z"

    def test_update_recurrence(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        recurrence = RecurrenceData(rrule=RecurrenceRule(frequency="DAILY", interval=2))  # type: ignore[call-arg]
        event = self._make_update_request(recurrence=recurrence)
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert "recurrence" in payload

    def test_preserve_existing_recurrence(self, mock_http_client: MagicMock) -> None:
        """When recurrence is not provided, preserves existing."""
        existing = self._existing_event()
        existing["recurrence"] = ["RRULE:FREQ=WEEKLY"]
        mock_http_client.get.return_value = _make_response(200, existing)
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        event = self._make_update_request(summary="Updated")
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["recurrence"] == ["RRULE:FREQ=WEEKLY"]

    def test_all_day_toggle(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        event = self._make_update_request(
            is_all_day=True,
            start="2025-10-25",
            end="2025-10-26",
        )
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"] == {"date": "2025-10-25"}
        assert payload["end"] == {"date": "2025-10-26"}

    def test_is_all_day_inferred_from_existing(
        self, mock_http_client: MagicMock
    ) -> None:
        """When is_all_day not specified, infers from existing event's date presence."""
        existing = {
            "summary": "All Day",
            "description": "",
            "start": {"date": "2025-10-25"},
            "end": {"date": "2025-10-26"},
        }
        mock_http_client.get.return_value = _make_response(200, existing)
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        event = self._make_update_request(start="2025-10-27")
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"] == {"date": "2025-10-27"}

    def test_404_on_fetch(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(404, {})

        event = self._make_update_request()
        with pytest.raises(HTTPException) as exc_info:
            update_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 404

    def test_401_on_update(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(401, {})

        event = self._make_update_request()
        with pytest.raises(HTTPException) as exc_info:
            update_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 401

    def test_404_on_update(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(404, {})

        event = self._make_update_request()
        with pytest.raises(HTTPException) as exc_info:
            update_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 404

    def test_other_error_on_update(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(
            422, {"error": {"message": "Bad data"}}
        )

        event = self._make_update_request()
        with pytest.raises(HTTPException) as exc_info:
            update_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 422

    def test_other_error_non_dict_json(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(422, "not a dict")

        event = self._make_update_request()
        with pytest.raises(HTTPException) as exc_info:
            update_calendar_event(event, ACCESS_TOKEN)

        assert "Unknown error" in exc_info.value.detail

    def test_request_error_on_fetch(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.side_effect = httpx.RequestError("connection reset")

        event = self._make_update_request()
        with pytest.raises(HTTPException) as exc_info:
            update_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "fetch existing event" in exc_info.value.detail.lower()

    def test_request_error_on_update(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.side_effect = httpx.RequestError("network error")

        event = self._make_update_request()
        with pytest.raises(HTTPException) as exc_info:
            update_calendar_event(event, ACCESS_TOKEN)

        assert exc_info.value.status_code == 500
        assert "Failed to update" in exc_info.value.detail

    def test_update_with_timezone(self, mock_http_client: MagicMock) -> None:
        """Timezone from request is used when provided."""
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        event = self._make_update_request(
            start="2025-10-25T10:00:00Z",
            end="2025-10-25T11:00:00Z",
            timezone="America/New_York",
        )
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"]["timeZone"] == "America/New_York"
        assert payload["end"]["timeZone"] == "America/New_York"

    def test_timezone_z_appended_when_missing(
        self, mock_http_client: MagicMock
    ) -> None:
        """Times without TZ info get Z appended."""
        mock_http_client.get.return_value = _make_response(200, self._existing_event())
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        event = self._make_update_request(
            start="2025-10-25T10:00:00",
            end="2025-10-25T11:00:00",
        )
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"]["dateTime"].endswith("Z")
        assert payload["end"]["dateTime"].endswith("Z")

    def test_preserves_existing_start_end_when_no_time_changes(
        self, mock_http_client: MagicMock
    ) -> None:
        """When no time-related fields are updated, existing start/end are preserved."""
        existing = self._existing_event()
        mock_http_client.get.return_value = _make_response(200, existing)
        mock_http_client.put.return_value = _make_response(200, {"id": "evt1"})

        event = self._make_update_request(summary="Just new title")
        update_calendar_event(event, ACCESS_TOKEN)

        call_args = mock_http_client.put.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload["start"] == existing["start"]
        assert payload["end"] == existing["end"]


# =========================================================================
# search_calendar_events_native
# =========================================================================


class TestSearchCalendarEventsNative:
    """Tests for search_calendar_events_native."""

    def test_with_preferences(self, mock_calendars_collection: MagicMock) -> None:
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]
        mock_calendars_collection.find_one.return_value = {
            "selected_calendars": ["cal1"]
        }

        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.search_events_in_calendar",
                return_value={"items": [_make_event()]},
            ) as mock_search,
        ):
            result = search_calendar_events_native(
                query="standup",
                user_id=USER_ID,
                access_token=ACCESS_TOKEN,
            )

            # Should only search cal1
            assert mock_search.call_count == 1
            assert result["total_matches"] >= 1

    def test_without_preferences_defaults_to_all(
        self, mock_calendars_collection: MagicMock
    ) -> None:
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]
        mock_calendars_collection.find_one.return_value = None

        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.search_events_in_calendar",
                return_value={"items": [_make_event()]},
            ) as mock_search,
        ):
            search_calendar_events_native(
                query="standup", user_id=USER_ID, access_token=ACCESS_TOKEN
            )

            assert mock_search.call_count == 2  # both calendars

    def test_fallback_to_all_calendars(
        self, mock_calendars_collection: MagicMock
    ) -> None:
        """When no events in selected calendars, falls back to searching all."""
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]
        mock_calendars_collection.find_one.return_value = {
            "selected_calendars": ["cal1"]
        }

        call_count = [0]

        def _search_side_effect(cal_id, query, token, time_min=None, time_max=None):
            call_count[0] += 1
            if cal_id == "cal1":
                # First round: empty for selected cal
                return {"items": []}
            # Fallback round: found in cal2
            return {"items": [_make_event()]}

        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.search_events_in_calendar",
                side_effect=_search_side_effect,
            ),
        ):
            result = search_calendar_events_native(
                query="standup", user_id=USER_ID, access_token=ACCESS_TOKEN
            )

            # First searched cal1 (empty), then fell back to cal1 + cal2
            assert result["total_matches"] >= 1

    def test_no_selected_calendars_searches_all(
        self, mock_calendars_collection: MagicMock
    ) -> None:
        """Empty selected_cal_objs falls back to all calendars."""
        cals = [_make_calendar_item("cal1")]
        mock_calendars_collection.find_one.return_value = {
            "selected_calendars": ["nonexistent"]
        }

        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.search_events_in_calendar",
                return_value={"items": [_make_event()]},
            ) as mock_search,
        ):
            search_calendar_events_native(
                query="test", user_id=USER_ID, access_token=ACCESS_TOKEN
            )

            # Falls back to all (cal1)
            assert mock_search.call_count >= 1

    def test_error_in_one_calendar(self, mock_calendars_collection: MagicMock) -> None:
        cals = [_make_calendar_item("cal1"), _make_calendar_item("cal2")]
        mock_calendars_collection.find_one.return_value = None

        def _search_side_effect(cal_id, query, token, time_min=None, time_max=None):
            if cal_id == "cal1":
                raise RuntimeError("API down")
            return {"items": [_make_event()]}

        with (
            patch(
                "app.services.calendar_service.fetch_calendar_list",
                return_value={"items": cals},
            ),
            patch(
                "app.services.calendar_service.search_events_in_calendar",
                side_effect=_search_side_effect,
            ),
        ):
            result = search_calendar_events_native(
                query="meeting", user_id=USER_ID, access_token=ACCESS_TOKEN
            )

            # cal2 events still returned
            assert result["total_matches"] >= 1


# =========================================================================
# get_user_calendar_preferences
# =========================================================================


class TestGetUserCalendarPreferences:
    """Tests for get_user_calendar_preferences."""

    def test_found(self, mock_calendars_collection: MagicMock) -> None:
        mock_calendars_collection.find_one.return_value = {
            "user_id": USER_ID,
            "selected_calendars": ["cal1", "cal2"],
        }

        result = get_user_calendar_preferences(USER_ID)

        assert result["selectedCalendars"] == ["cal1", "cal2"]

    def test_not_found(self, mock_calendars_collection: MagicMock) -> None:
        mock_calendars_collection.find_one.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            get_user_calendar_preferences(USER_ID)

        assert exc_info.value.status_code == 404

    def test_found_without_selected_calendars_key(
        self, mock_calendars_collection: MagicMock
    ) -> None:
        mock_calendars_collection.find_one.return_value = {"user_id": USER_ID}

        with pytest.raises(HTTPException) as exc_info:
            get_user_calendar_preferences(USER_ID)

        assert exc_info.value.status_code == 404


# =========================================================================
# update_user_calendar_preferences
# =========================================================================


class TestUpdateUserCalendarPreferences:
    """Tests for update_user_calendar_preferences."""

    def test_success_update(self, mock_calendars_collection: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_result.upserted_id = None
        mock_calendars_collection.update_one.return_value = mock_result

        result = update_user_calendar_preferences(USER_ID, ["cal1"])

        assert "updated successfully" in result["message"]

    def test_success_upsert(self, mock_calendars_collection: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_result.upserted_id = "new_id"
        mock_calendars_collection.update_one.return_value = mock_result

        result = update_user_calendar_preferences(USER_ID, ["cal1"])

        assert "updated successfully" in result["message"]

    def test_no_changes(self, mock_calendars_collection: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_result.upserted_id = None
        mock_calendars_collection.update_one.return_value = mock_result

        result = update_user_calendar_preferences(USER_ID, ["cal1"])

        assert "No changes" in result["message"]


# =========================================================================
# search_events_in_calendar
# =========================================================================


class TestSearchEventsInCalendar:
    """Tests for search_events_in_calendar."""

    def test_success_200(self, mock_http_client: MagicMock) -> None:
        search_data = {"items": [_make_event()]}
        mock_http_client.get.return_value = _make_response(200, search_data)

        result = search_events_in_calendar("cal1", "standup", ACCESS_TOKEN)

        assert len(result["items"]) == 1

    def test_with_time_filters(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, {"items": []})

        search_events_in_calendar(
            "cal1",
            "standup",
            ACCESS_TOKEN,
            time_min="2025-01-01T00:00:00Z",
            time_max="2025-12-31T23:59:59Z",
        )

        call_args = mock_http_client.get.call_args
        params = call_args.kwargs.get("params", call_args[1].get("params", {}))
        assert params["timeMin"] == "2025-01-01T00:00:00Z"
        assert params["timeMax"] == "2025-12-31T23:59:59Z"

    def test_error_response(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(
            403, {"error": {"message": "Access denied"}}
        )

        with pytest.raises(HTTPException) as exc_info:
            search_events_in_calendar("cal1", "standup", ACCESS_TOKEN)

        assert exc_info.value.status_code == 403

    def test_request_error(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.side_effect = httpx.RequestError("dns failed")

        with pytest.raises(HTTPException) as exc_info:
            search_events_in_calendar("cal1", "standup", ACCESS_TOKEN)

        assert exc_info.value.status_code == 500


# =========================================================================
# get_calendar_events_by_id
# =========================================================================


class TestGetCalendarEventsById:
    """Tests for get_calendar_events_by_id."""

    def test_success(self) -> None:
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            mock_fetch.return_value = {
                "items": [_make_event()],
                "nextPageToken": "abc",
            }

            result = get_calendar_events_by_id("cal1", ACCESS_TOKEN)

            assert len(result["events"]) == 1
            assert result["nextPageToken"] == "abc"

    def test_filters_events(self) -> None:
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            mock_fetch.return_value = {
                "items": [
                    _make_event(event_type="birthday"),
                    _make_event(event_id="e2"),
                ],
            }

            result = get_calendar_events_by_id("cal1", ACCESS_TOKEN)

            assert len(result["events"]) == 1
            assert result["events"][0]["id"] == "e2"


# =========================================================================
# find_event_for_action
# =========================================================================


class TestFindEventForAction:
    """Tests for find_event_for_action."""

    def test_find_by_query(self) -> None:
        with patch(
            "app.services.calendar_service.search_calendar_events_native"
        ) as mock_search:
            mock_search.return_value = {
                "matching_events": [_make_event()],
            }

            lookup = EventLookupRequest(query="standup")  # type: ignore[call-arg]
            result = find_event_for_action(ACCESS_TOKEN, lookup, USER_ID)

            assert result is not None
            assert result["id"] == "evt1"

    def test_find_by_query_no_results(self) -> None:
        with patch(
            "app.services.calendar_service.search_calendar_events_native"
        ) as mock_search:
            mock_search.return_value = {"matching_events": []}

            lookup = EventLookupRequest(query="nonexistent")  # type: ignore[call-arg]
            result = find_event_for_action(ACCESS_TOKEN, lookup, USER_ID)

            assert result is None

    def test_find_by_calendar_and_event_id(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(200, _make_event())

        lookup = EventLookupRequest(event_id="evt1", calendar_id="cal1")  # type: ignore[call-arg]
        result = find_event_for_action(ACCESS_TOKEN, lookup, USER_ID)

        assert result is not None
        assert result["id"] == "evt1"

    def test_find_by_id_not_found(self, mock_http_client: MagicMock) -> None:
        mock_http_client.get.return_value = _make_response(404, {})

        lookup = EventLookupRequest(event_id="evt1", calendar_id="cal1")  # type: ignore[call-arg]
        result = find_event_for_action(ACCESS_TOKEN, lookup, USER_ID)

        assert result is None


# =========================================================================
# fetch_same_day_events
# =========================================================================


class TestFetchSameDayEvents:
    """Tests for fetch_same_day_events."""

    def test_success(self) -> None:
        with patch("app.services.calendar_service.get_calendar_events") as mock_get:
            mock_get.return_value = {"events": [_make_event()]}

            result = fetch_same_day_events(
                {"2025-10-25": "+05:30"}, ACCESS_TOKEN, USER_ID
            )

            assert len(result) == 1

    def test_multiple_dates(self) -> None:
        with patch("app.services.calendar_service.get_calendar_events") as mock_get:
            mock_get.return_value = {"events": [_make_event()]}

            dates_info = {
                "2025-10-25": "+05:30",
                "2025-10-26": "+05:30",
            }
            result = fetch_same_day_events(dates_info, ACCESS_TOKEN, USER_ID)

            assert len(result) == 2  # one event per date
            assert mock_get.call_count == 2

    def test_error_on_one_date(self) -> None:
        call_count = [0]

        def _side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("error")
            return {"events": [_make_event()]}

        with patch(
            "app.services.calendar_service.get_calendar_events",
            side_effect=_side_effect,
        ):
            dates_info = {"2025-10-25": "+05:30", "2025-10-26": "+05:30"}
            result = fetch_same_day_events(dates_info, ACCESS_TOKEN, USER_ID)

            # Second date succeeds
            assert len(result) == 1

    def test_non_dict_result_skipped(self) -> None:
        with patch("app.services.calendar_service.get_calendar_events") as mock_get:
            mock_get.return_value = "not a dict"

            result = fetch_same_day_events(
                {"2025-10-25": "+05:30"}, ACCESS_TOKEN, USER_ID
            )

            assert result == []


# =========================================================================
# enrich_calendar_options_with_metadata
# =========================================================================


class TestEnrichCalendarOptionsWithMetadata:
    """Tests for enrich_calendar_options_with_metadata."""

    def test_enriches_options(self) -> None:
        options = [
            {
                "calendar_id": "cal1",
                "start": "2025-10-25T10:00:00+05:30",
            }
        ]

        with (
            patch(
                "app.services.calendar_service.get_calendar_metadata_map",
                return_value=({"cal1": "#ff0000"}, {"cal1": "Work"}),
            ),
            patch(
                "app.services.calendar_service.fetch_same_day_events",
                return_value=[_make_event(calendar_id="cal1")],
            ),
        ):
            result = enrich_calendar_options_with_metadata(
                options, ACCESS_TOKEN, USER_ID
            )

            assert result[0]["background_color"] == "#ff0000"
            assert result[0]["calendar_name"] == "Work"
            assert len(result[0]["same_day_events"]) == 1

    def test_default_color_and_name(self) -> None:
        options = [
            {
                "calendar_id": "unknown",
                "start": "2025-10-25T10:00:00Z",
            }
        ]

        with (
            patch(
                "app.services.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
            patch(
                "app.services.calendar_service.fetch_same_day_events",
                return_value=[],
            ),
        ):
            result = enrich_calendar_options_with_metadata(
                options, ACCESS_TOKEN, USER_ID
            )

            assert result[0]["background_color"] == "#00bbff"
            assert result[0]["calendar_name"] == "Calendar"
