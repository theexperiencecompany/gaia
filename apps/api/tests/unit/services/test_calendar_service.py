"""Unit tests for the calendar service (app/services/calendar_service.py).

After the Composio proxy migration, every Calendar API call routes through
`proxy_request_sync`. Tests mock that helper directly and assert on the
shape of each request (toolkit + endpoint + method + body + query).
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
import pytest

from app.models.calendar_models import (
    EventCreateRequest,
    EventDeleteRequest,
    EventLookupRequest,
    EventUpdateRequest,
)
from app.services.calendar_service import (
    create_calendar_event,
    delete_calendar_event,
    extract_unique_dates,
    fetch_calendar_events,
    fetch_calendar_list,
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
from app.utils.errors import AppError

USER_ID = "user_test_123"
PROXY_PATH = "app.services.calendar_service.proxy_request_sync"


@pytest.fixture
def mock_proxy() -> Iterator[MagicMock]:
    with patch(PROXY_PATH) as proxy:
        proxy.return_value = {}
        yield proxy


@pytest.fixture
def mock_calendars_collection() -> Iterator[MagicMock]:
    with patch("app.services.calendar_service.calendars_collection") as col:
        yield col


def _http_error(status: int, body: dict[str, Any] | None = None) -> AppError:
    return AppError(
        message=f"GOOGLECALENDAR API error ({status})",
        status_code=status,
        meta={"provider_response": body or {}},
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestFilterEvents:
    def test_drops_birthdays(self):
        events = [
            {"eventType": "birthday", "start": {"date": "2025-01-01"}},
            {"eventType": "default", "start": {"date": "2025-01-02"}},
        ]
        assert filter_events(events) == [{"eventType": "default", "start": {"date": "2025-01-02"}}]

    def test_drops_events_without_start(self):
        events = [
            {"eventType": "default"},
            {"eventType": "default", "start": {}},
            {"eventType": "default", "start": {"dateTime": "2025-01-01T10:00"}},
        ]
        assert filter_events(events) == [
            {"eventType": "default", "start": {"dateTime": "2025-01-01T10:00"}}
        ]


class TestExtractUniqueDates:
    def test_extracts_dates_with_offsets(self):
        result = extract_unique_dates(
            [
                {"start": "2025-10-25T09:00:00+05:30"},
                {"start": "2025-10-25T11:00:00+05:30"},
                {"start": "2025-10-26T09:00:00Z"},
            ]
        )
        assert result == {"2025-10-25": "+05:30", "2025-10-26": "+00:00"}

    def test_skips_missing_start(self):
        assert extract_unique_dates([{"start": ""}, {}]) == {}


class TestFormatEventForFrontend:
    def test_uses_metadata_maps(self):
        event = {
            "summary": "Lunch",
            "start": {"dateTime": "2025-01-15T12:00"},
            "end": {"dateTime": "2025-01-15T13:00"},
            "calendarId": "cal-1",
        }
        formatted = format_event_for_frontend(event, {"cal-1": "#abc"}, {"cal-1": "Work"})
        assert formatted == {
            "summary": "Lunch",
            "start_time": "2025-01-15T12:00",
            "end_time": "2025-01-15T13:00",
            "calendar_name": "Work",
            "background_color": "#abc",
        }


# ---------------------------------------------------------------------------
# fetch_calendar_list / list_calendars / metadata
# ---------------------------------------------------------------------------


class TestFetchCalendarList:
    def test_returns_full_data(self, mock_proxy):
        items = [
            {
                "id": "cal-1",
                "summary": "Work",
                "description": "d",
                "backgroundColor": "#abc",
            }
        ]
        mock_proxy.return_value = {"items": items}
        result = fetch_calendar_list(USER_ID)
        assert result == {"items": items}
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["toolkit"] == "GOOGLECALENDAR"
        assert kwargs["endpoint"].endswith("/users/me/calendarList")
        assert kwargs["method"] == "GET"
        assert kwargs["user_id"] == USER_ID

    def test_short_format_returns_subset(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [
                {
                    "id": "c1",
                    "summary": "A",
                    "description": "x",
                    "backgroundColor": "#1",
                }
            ]
        }
        result = fetch_calendar_list(USER_ID, short=True)
        assert result == [{"id": "c1", "summary": "A", "description": "x", "backgroundColor": "#1"}]

    def test_propagates_proxy_error_as_http_exception(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500, {"error": {"message": "boom"}})
        with pytest.raises(HTTPException) as exc:
            fetch_calendar_list(USER_ID)
        assert exc.value.status_code == 500
        assert "boom" in str(exc.value.detail)


class TestListCalendars:
    def test_delegates_to_fetch_calendar_list(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        list_calendars(USER_ID, short=True)
        assert mock_proxy.call_args.kwargs["user_id"] == USER_ID


class TestGetCalendarMetadataMap:
    def test_returns_color_and_name_maps(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [
                {"id": "c1", "summary": "Work", "backgroundColor": "#fff"},
                {"id": "c2", "summary": "Home", "backgroundColor": "#00bbff"},
            ]
        }
        color_map, name_map = get_calendar_metadata_map(USER_ID)
        assert color_map == {"c1": "#fff", "c2": "#00bbff"}
        assert name_map == {"c1": "Work", "c2": "Home"}


# ---------------------------------------------------------------------------
# fetch_calendar_events / search
# ---------------------------------------------------------------------------


class TestFetchCalendarEvents:
    def test_passes_query_params(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        fetch_calendar_events(
            "primary",
            USER_ID,
            page_token="tk",
            time_min="2025-01-01T00:00:00Z",
            time_max="2025-01-02T00:00:00Z",
            max_results=42,
        )
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["endpoint"].endswith("/calendars/primary/events")
        assert kwargs["method"] == "GET"
        assert kwargs["query"]["maxResults"] == 42
        assert kwargs["query"]["pageToken"] == "tk"
        assert kwargs["query"]["timeMin"] == "2025-01-01T00:00:00Z"
        assert kwargs["query"]["timeMax"] == "2025-01-02T00:00:00Z"
        assert kwargs["query"]["singleEvents"] == "true"


class TestSearchEventsInCalendar:
    def test_search_query_in_params(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        search_events_in_calendar("primary", "lunch", USER_ID)
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["query"]["q"] == "lunch"
        assert kwargs["query"]["maxResults"] == 50

    def test_propagates_error(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500)
        with pytest.raises(HTTPException):
            search_events_in_calendar("primary", "lunch", USER_ID)


# ---------------------------------------------------------------------------
# create / update / delete
# ---------------------------------------------------------------------------


class TestCreateCalendarEvent:
    def test_creates_time_specific_event(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt-1", "htmlLink": "x"}
        event = EventCreateRequest(
            summary="Sync",
            description="",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
            timezone="UTC",
        )
        result = create_calendar_event(event, USER_ID)
        assert result["id"] == "evt-1"
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["method"] == "POST"
        assert kwargs["endpoint"].endswith("/calendars/primary/events")
        body = kwargs["body"]
        assert body["summary"] == "Sync"
        assert body["start"]["dateTime"] == "2025-01-15T10:00:00Z"
        assert body["end"]["dateTime"] == "2025-01-15T11:00:00Z"

    def test_all_day_event(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="Vacation",
            description="",
            is_all_day=True,
            start="2025-01-15",
            end="2025-01-16",
        )
        create_calendar_event(event, USER_ID)
        body = mock_proxy.call_args.kwargs["body"]
        assert body["start"] == {"date": "2025-01-15"}
        assert body["end"] == {"date": "2025-01-16"}

    def test_with_meeting_room_adds_conference_data(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="Meet",
            description="",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
            create_meeting_room=True,
        )
        create_calendar_event(event, USER_ID)
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["body"]["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {
            "type": "hangoutsMeet"
        }
        assert kwargs["query"]["conferenceDataVersion"] == "1"

    def test_missing_start_for_timed_event_raises(self, mock_proxy):
        event = EventCreateRequest(
            summary="x",
            description="",
            is_all_day=False,
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
        )
        # Force start/end to None to trigger the service-level validation.
        # The Pydantic model rejects empty strings, so we mutate after construction.
        event.start = None
        event.end = None
        with pytest.raises(HTTPException) as exc:
            create_calendar_event(event, USER_ID)
        assert exc.value.status_code == 400


class TestDeleteCalendarEvent:
    def test_deletes_event(self, mock_proxy):
        mock_proxy.return_value = None
        result = delete_calendar_event(
            EventDeleteRequest(event_id="evt-1", calendar_id="primary"), USER_ID
        )
        assert result == {"success": True, "message": "Event deleted successfully"}
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["method"] == "DELETE"
        assert kwargs["endpoint"].endswith("/calendars/primary/events/evt-1")

    def test_404_raises_clean_message(self, mock_proxy):
        mock_proxy.side_effect = _http_error(404)
        with pytest.raises(HTTPException) as exc:
            delete_calendar_event(EventDeleteRequest(event_id="x", calendar_id="primary"), USER_ID)
        assert exc.value.status_code == 404
        assert "Event not found" in str(exc.value.detail)


class TestUpdateCalendarEvent:
    def test_updates_summary(self, mock_proxy):
        mock_proxy.side_effect = [
            {"summary": "Old", "description": "d", "start": {}, "end": {}},
            {"id": "evt", "summary": "New"},
        ]
        result = update_calendar_event(
            EventUpdateRequest(event_id="evt", calendar_id="primary", summary="New"),
            USER_ID,
        )
        assert result["calendarId"] == "primary"
        # Two calls: GET existing + PUT update
        assert mock_proxy.call_args_list[0].kwargs["method"] == "GET"
        assert mock_proxy.call_args_list[1].kwargs["method"] == "PUT"
        assert mock_proxy.call_args_list[1].kwargs["body"]["summary"] == "New"


class TestFindEventForAction:
    def test_returns_none_when_not_found(self, mock_proxy):
        mock_proxy.side_effect = _http_error(404)
        result = find_event_for_action(
            USER_ID, EventLookupRequest(calendar_id="primary", event_id="missing")
        )
        assert result is None


# ---------------------------------------------------------------------------
# Higher-level orchestration
# ---------------------------------------------------------------------------


class TestGetCalendarEvents:
    def test_uses_existing_preferences(self, mock_proxy, mock_calendars_collection):
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        mock_calendars_collection.find_one.return_value = {"selected_calendars": ["c1"]}
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            mock_fetch.return_value = {"items": []}
            result = get_calendar_events(USER_ID)
        assert result["selectedCalendars"] == ["c1"]

    def test_seeds_preferences_when_missing(self, mock_proxy, mock_calendars_collection):
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        mock_calendars_collection.find_one.return_value = None
        with patch("app.services.calendar_service.fetch_calendar_events") as mock_fetch:
            mock_fetch.return_value = {"items": []}
            get_calendar_events(USER_ID)
        mock_calendars_collection.update_one.assert_called_once()


class TestGetCalendarEventsById:
    def test_returns_filtered_events(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [
                {"start": {"dateTime": "2025-01-01T10:00"}, "id": "e1"},
                {"eventType": "birthday", "start": {"date": "2025-01-02"}, "id": "e2"},
            ],
            "nextPageToken": "tk",
        }
        result = get_calendar_events_by_id("primary", USER_ID)
        assert len(result["events"]) == 1
        assert result["events"][0]["id"] == "e1"
        assert result["nextPageToken"] == "tk"


class TestSearchCalendarEventsNative:
    def test_searches_selected_calendars(self, mock_proxy, mock_calendars_collection):
        mock_calendars_collection.find_one.return_value = {"selected_calendars": ["c1"]}
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        with patch("app.services.calendar_service.search_events_in_calendar") as mock_search:
            mock_search.return_value = {
                "items": [
                    {
                        "id": "e1",
                        "start": {"dateTime": "2025-01-01T10:00"},
                    }
                ]
            }
            result = search_calendar_events_native("foo", USER_ID)
        assert result["total_matches"] == 1


# ---------------------------------------------------------------------------
# Preferences (DB-only)
# ---------------------------------------------------------------------------


class TestPreferences:
    def test_get_returns_selected_calendars(self, mock_calendars_collection):
        mock_calendars_collection.find_one.return_value = {"selected_calendars": ["c1"]}
        assert get_user_calendar_preferences(USER_ID) == {"selectedCalendars": ["c1"]}

    def test_get_raises_when_missing(self, mock_calendars_collection):
        mock_calendars_collection.find_one.return_value = None
        with pytest.raises(HTTPException) as exc:
            get_user_calendar_preferences(USER_ID)
        assert exc.value.status_code == 404

    def test_update_returns_success_message(self, mock_calendars_collection):
        result_mock = MagicMock(modified_count=1, upserted_id=None)
        mock_calendars_collection.update_one.return_value = result_mock
        assert update_user_calendar_preferences(USER_ID, ["c1"]) == {
            "message": "Calendar preferences updated successfully"
        }


class TestInitializeCalendarPreferences:
    def test_skips_when_already_set(self, mock_proxy, mock_calendars_collection):
        mock_calendars_collection.find_one.return_value = {"selected_calendars": ["c1"]}
        initialize_calendar_preferences(USER_ID)
        mock_calendars_collection.update_one.assert_not_called()
        mock_proxy.assert_not_called()

    def test_seeds_when_empty(self, mock_proxy, mock_calendars_collection):
        mock_calendars_collection.find_one.return_value = None
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        initialize_calendar_preferences(USER_ID)
        mock_calendars_collection.update_one.assert_called_once()
        update_args: list[Any] = mock_calendars_collection.update_one.call_args[0]
        assert update_args[1] == {"$set": {"selected_calendars": ["c1", "c2"]}}
