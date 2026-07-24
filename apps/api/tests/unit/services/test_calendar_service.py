"""Unit tests for the calendar service (app/services/calendar_service.py).

Every Google Calendar API call routes through the async Composio
``proxy_request``; preferences go through ``calendar_repository``. Tests mock
those two seams and assert the shape of each request. Pure helpers
(``filter_events``/``format_event_for_frontend``) stay synchronous.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.models.calendar_models import (
    CalendarPreferencesDocument,
    EventCreateRequest,
    EventDeleteRequest,
    EventUpdateRequest,
)
from app.services.calendar_service import (
    create_calendar_event,
    delete_calendar_event,
    fetch_calendar_events,
    fetch_calendar_list,
    filter_events,
    format_event_for_frontend,
    get_calendar_events,
    get_calendar_events_by_id,
    get_calendar_metadata_map,
    get_user_calendar_preferences,
    list_calendars,
    search_calendar_events_native,
    search_events_in_calendar,
    update_calendar_event,
    update_user_calendar_preferences,
)
from app.utils.errors import AppError

USER_ID = "user_test_123"
PROXY_PATH = "app.services.calendar_service.proxy_request"


@pytest.fixture
def mock_proxy() -> Iterator[AsyncMock]:
    with patch(PROXY_PATH, new_callable=AsyncMock) as proxy:
        proxy.return_value = {}
        yield proxy


@pytest.fixture
def mock_calendar_repo() -> Iterator[AsyncMock]:
    with patch("app.services.calendar_service.calendar_repository", new_callable=AsyncMock) as repo:
        repo.get_for_user.return_value = None
        repo.set_selected_calendars.return_value = True
        yield repo


def _prefs(selected: list[str]) -> CalendarPreferencesDocument:
    return CalendarPreferencesDocument(user_id=USER_ID, selected_calendars=selected)


def _http_error(status: int, body: dict[str, Any] | None = None) -> AppError:
    return AppError(
        message=f"GOOGLECALENDAR API error ({status})",
        status_code=status,
        meta={"provider_response": body or {}},
    )


# ---------------------------------------------------------------------------
# Pure helpers (synchronous)
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
    async def test_returns_full_data(self, mock_proxy):
        items = [{"id": "cal-1", "summary": "Work", "description": "d", "backgroundColor": "#abc"}]
        mock_proxy.return_value = {"items": items}
        result = await fetch_calendar_list(USER_ID)
        assert result == {"items": items}
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["toolkit"] == "GOOGLECALENDAR"
        assert kwargs["endpoint"].endswith("/users/me/calendarList")
        assert kwargs["method"] == "GET"
        assert kwargs["user_id"] == USER_ID

    async def test_short_format_returns_subset(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [{"id": "c1", "summary": "A", "description": "x", "backgroundColor": "#1"}]
        }
        result = await fetch_calendar_list(USER_ID, short=True)
        assert result == [{"id": "c1", "summary": "A", "description": "x", "backgroundColor": "#1"}]

    async def test_propagates_proxy_error_as_http_exception(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500, {"error": {"message": "boom"}})
        with pytest.raises(HTTPException) as exc:
            await fetch_calendar_list(USER_ID)
        assert exc.value.status_code == 500
        assert "boom" in str(exc.value.detail)


class TestListCalendars:
    async def test_delegates_to_fetch_calendar_list(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        await list_calendars(USER_ID, short=True)
        assert mock_proxy.call_args.kwargs["user_id"] == USER_ID


class TestGetCalendarMetadataMap:
    async def test_returns_color_and_name_maps(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [
                {"id": "c1", "summary": "Work", "backgroundColor": "#fff"},
                {"id": "c2", "summary": "Home", "backgroundColor": "#00bbff"},
            ]
        }
        color_map, name_map = await get_calendar_metadata_map(USER_ID)
        assert color_map == {"c1": "#fff", "c2": "#00bbff"}
        assert name_map == {"c1": "Work", "c2": "Home"}


# ---------------------------------------------------------------------------
# fetch_calendar_events / search
# ---------------------------------------------------------------------------


class TestFetchCalendarEvents:
    async def test_passes_query_params(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        await fetch_calendar_events(
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
    async def test_search_query_in_params(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        await search_events_in_calendar("primary", "lunch", USER_ID)
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["query"]["q"] == "lunch"
        assert kwargs["query"]["maxResults"] == 50

    async def test_propagates_error(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500)
        with pytest.raises(HTTPException):
            await search_events_in_calendar("primary", "lunch", USER_ID)


# ---------------------------------------------------------------------------
# create / update / delete
# ---------------------------------------------------------------------------


class TestCreateCalendarEvent:
    async def test_creates_time_specific_event(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt-1", "htmlLink": "x"}
        event = EventCreateRequest(
            summary="Sync",
            description="",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
            timezone="UTC",
        )
        result = await create_calendar_event(event, USER_ID)
        assert result["id"] == "evt-1"
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["method"] == "POST"
        assert kwargs["endpoint"].endswith("/calendars/primary/events")
        body = kwargs["body"]
        assert body["summary"] == "Sync"
        assert body["start"]["dateTime"] == "2025-01-15T10:00:00Z"
        assert body["end"]["dateTime"] == "2025-01-15T11:00:00Z"

    async def test_all_day_event(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="Vacation",
            description="",
            is_all_day=True,
            start="2025-01-15",
            end="2025-01-16",
        )
        await create_calendar_event(event, USER_ID)
        body = mock_proxy.call_args.kwargs["body"]
        assert body["start"] == {"date": "2025-01-15"}
        assert body["end"] == {"date": "2025-01-16"}

    async def test_with_meeting_room_adds_conference_data(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="Meet",
            description="",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
            create_meeting_room=True,
        )
        await create_calendar_event(event, USER_ID)
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["body"]["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {
            "type": "hangoutsMeet"
        }
        assert kwargs["query"]["conferenceDataVersion"] == "1"

    async def test_missing_start_for_timed_event_raises(self, mock_proxy):
        event = EventCreateRequest(
            summary="x",
            description="",
            is_all_day=False,
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
        )
        # The Pydantic model rejects empty strings, so mutate after construction.
        event.start = None
        event.end = None
        with pytest.raises(HTTPException) as exc:
            await create_calendar_event(event, USER_ID)
        assert exc.value.status_code == 400


class TestDeleteCalendarEvent:
    async def test_deletes_event(self, mock_proxy):
        mock_proxy.return_value = None
        result = await delete_calendar_event(
            EventDeleteRequest(event_id="evt-1", calendar_id="primary"), USER_ID
        )
        assert result == {"success": True, "message": "Event deleted successfully"}
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["method"] == "DELETE"
        assert kwargs["endpoint"].endswith("/calendars/primary/events/evt-1")

    async def test_404_raises_clean_message(self, mock_proxy):
        mock_proxy.side_effect = _http_error(404)
        with pytest.raises(HTTPException) as exc:
            await delete_calendar_event(
                EventDeleteRequest(event_id="x", calendar_id="primary"), USER_ID
            )
        assert exc.value.status_code == 404
        assert "Event not found" in str(exc.value.detail)


class TestUpdateCalendarEvent:
    async def test_updates_summary(self, mock_proxy):
        mock_proxy.side_effect = [
            {"summary": "Old", "description": "d", "start": {}, "end": {}},
            {"id": "evt", "summary": "New"},
        ]
        result = await update_calendar_event(
            EventUpdateRequest(event_id="evt", calendar_id="primary", summary="New"),
            USER_ID,
        )
        assert result["calendarId"] == "primary"
        # Two calls: GET existing + PUT update
        assert mock_proxy.call_args_list[0].kwargs["method"] == "GET"
        assert mock_proxy.call_args_list[1].kwargs["method"] == "PUT"
        assert mock_proxy.call_args_list[1].kwargs["body"]["summary"] == "New"


# ---------------------------------------------------------------------------
# Higher-level orchestration
# ---------------------------------------------------------------------------


class TestGetCalendarEvents:
    async def test_uses_existing_preferences(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = {"items": []}
            result = await get_calendar_events(USER_ID)
        assert result["selectedCalendars"] == ["c1"]

    async def test_seeds_preferences_when_missing(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        mock_calendar_repo.get_for_user.return_value = None
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = {"items": []}
            await get_calendar_events(USER_ID)
        mock_calendar_repo.set_selected_calendars.assert_awaited_once()


class TestGetCalendarEventsById:
    async def test_returns_filtered_events(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [
                {"start": {"dateTime": "2025-01-01T10:00"}, "id": "e1"},
                {"eventType": "birthday", "start": {"date": "2025-01-02"}, "id": "e2"},
            ],
            "nextPageToken": "tk",
        }
        result = await get_calendar_events_by_id("primary", USER_ID)
        assert len(result["events"]) == 1
        assert result["events"][0]["id"] == "e1"
        assert result["nextPageToken"] == "tk"


class TestSearchCalendarEventsNative:
    async def test_searches_selected_calendars(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = {
                "items": [{"id": "e1", "start": {"dateTime": "2025-01-01T10:00"}}]
            }
            result = await search_calendar_events_native("foo", USER_ID)
        assert result["total_matches"] == 1


# ---------------------------------------------------------------------------
# Preferences (repository-backed)
# ---------------------------------------------------------------------------


class TestPreferences:
    async def test_get_returns_selected_calendars(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        assert await get_user_calendar_preferences(USER_ID) == {"selectedCalendars": ["c1"]}

    async def test_get_raises_when_missing(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_user_calendar_preferences(USER_ID)
        assert exc.value.status_code == 404

    async def test_update_returns_success_message(self, mock_calendar_repo):
        mock_calendar_repo.set_selected_calendars.return_value = True
        assert await update_user_calendar_preferences(USER_ID, ["c1"]) == {
            "message": "Calendar preferences updated successfully"
        }

    async def test_update_no_change_message(self, mock_calendar_repo):
        mock_calendar_repo.set_selected_calendars.return_value = False
        assert await update_user_calendar_preferences(USER_ID, ["c1"]) == {
            "message": "No changes made to calendar preferences"
        }
