"""Unit tests for the calendar service (app/services/calendar_service.py).

Every Google Calendar API call routes through the async Composio
``proxy_request``; preferences go through ``calendar_repository``. Tests mock
those two seams and assert the shape of each request. Pure helpers
(``filter_events``/``format_event_for_frontend``) stay synchronous, and the
private date/recurrence/bounds helpers are exercised directly since the public
surface does not reach every branch.
"""

from collections.abc import Iterator
from datetime import datetime
import re
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.constants.calendar import DEFAULT_CALENDAR_COLOR
from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.models.calendar_models import (
    CalendarEventDisplay,
    CalendarPreferencesDocument,
    CalendarPreferencesResponse,
    CalendarPreferencesUpdateResponse,
    EventCreateRequest,
    EventDeleteRequest,
    EventDeleteResponse,
    EventUpdateRequest,
    GoogleCalendarEventDateTime,
    GoogleCalendarEventResource,
    GoogleCalendarEventsPage,
    GoogleCalendarEventWrite,
    GoogleCalendarListEntry,
    RecurrenceData,
    RecurrenceRule,
)
from app.services.calendar_service import (
    _all_day_bounds,
    _create_recurrence_rules,
    _date_part,
    _event_sort_key,
    _merge_event_bounds,
    _proxy,
    _resolve_selected_calendars,
    _tag_with_source_calendar,
    _timed_bounds,
    _update_recurrence_rules,
    _with_utc_suffix,
    create_calendar_event,
    delete_calendar_event,
    fetch_all_calendar_events,
    fetch_calendar_events,
    filter_events,
    format_event_for_frontend,
    get_calendar_events,
    get_calendar_events_by_id,
    get_calendar_metadata_map,
    get_user_calendar_preferences,
    list_calendars,
    search_calendar_events_native,
    search_events_in_calendar,
    to_calendar_summaries,
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


class _BadRecurrence:
    """A recurrence object whose Google formatting raises — pins the fail-loud
    HTTPException path of the recurrence-rule helpers."""

    def to_google_calendar_format(self) -> list[str]:
        raise ValueError("boom")


# ---------------------------------------------------------------------------
# Pure helpers (synchronous)
# ---------------------------------------------------------------------------


class TestFilterEvents:
    def test_drops_birthdays(self):
        events = [
            GoogleCalendarEventResource(
                id="b", eventType="birthday", start=GoogleCalendarEventDateTime(date="2025-01-01")
            ),
            GoogleCalendarEventResource(
                id="d", eventType="default", start=GoogleCalendarEventDateTime(date="2025-01-02")
            ),
        ]
        kept = filter_events(events)
        assert [event.id for event in kept] == ["d"]
        assert kept[0].start is not None
        assert kept[0].start.date == "2025-01-02"

    def test_drops_events_without_start(self):
        events = [
            GoogleCalendarEventResource(id="no-start", eventType="default"),
            GoogleCalendarEventResource(
                id="empty-start", eventType="default", start=GoogleCalendarEventDateTime()
            ),
            GoogleCalendarEventResource(
                id="timed",
                eventType="default",
                start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00"),
            ),
        ]
        assert [event.id for event in filter_events(events)] == ["timed"]


class TestFormatEventForFrontend:
    def test_uses_metadata_maps(self):
        event = GoogleCalendarEventResource(
            summary="Lunch",
            start=GoogleCalendarEventDateTime(dateTime="2025-01-15T12:00"),
            end=GoogleCalendarEventDateTime(dateTime="2025-01-15T13:00"),
            calendarId="cal-1",
        )
        formatted = format_event_for_frontend(event, {"cal-1": "#abc"}, {"cal-1": "Work"})
        assert formatted == CalendarEventDisplay(
            summary="Lunch",
            start_time="2025-01-15T12:00",
            end_time="2025-01-15T13:00",
            calendar_name="Work",
            background_color="#abc",
        )

    def test_falls_back_to_defaults(self):
        formatted = format_event_for_frontend(GoogleCalendarEventResource(), {}, {})
        assert formatted == CalendarEventDisplay(
            summary="No Title",
            start_time="",
            end_time="",
            calendar_name="Unknown Calendar",
            background_color=DEFAULT_CALENDAR_COLOR,
        )

    def test_all_day_event_uses_dates(self):
        event = GoogleCalendarEventResource(
            summary="Holiday",
            start=GoogleCalendarEventDateTime(date="2025-01-01"),
            end=GoogleCalendarEventDateTime(date="2025-01-02"),
            calendarId="cal-1",
        )
        formatted = format_event_for_frontend(event, {"cal-1": "#abc"}, {"cal-1": "Work"})
        assert formatted.start_time == "2025-01-01"
        assert formatted.end_time == "2025-01-02"

    def test_date_time_preferred_over_date(self):
        event = GoogleCalendarEventResource(
            summary="Mixed",
            start=GoogleCalendarEventDateTime(date="2025-01-01", dateTime="2025-01-01T10:00"),
            end=GoogleCalendarEventDateTime(date="2025-01-01", dateTime="2025-01-01T11:00"),
        )
        formatted = format_event_for_frontend(event, {}, {})
        assert formatted.start_time == "2025-01-01T10:00"
        assert formatted.end_time == "2025-01-01T11:00"

    def test_calendar_title_fallback_when_not_in_maps(self):
        event = GoogleCalendarEventResource(
            summary="Imported",
            start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00"),
            calendarId="cal-9",
            calendarTitle="Imported Cal",
        )
        formatted = format_event_for_frontend(event, {"cal-1": "#abc"}, {"cal-1": "Work"})
        assert formatted.calendar_name == "Imported Cal"
        assert formatted.background_color == DEFAULT_CALENDAR_COLOR

    def test_empty_start_and_end_objects_fall_back_to_empty_strings(self):
        event = GoogleCalendarEventResource(
            summary="x", start=GoogleCalendarEventDateTime(), end=GoogleCalendarEventDateTime()
        )
        formatted = format_event_for_frontend(event, {}, {"": "Empty Cal"})
        assert formatted.start_time == ""
        assert formatted.end_time == ""
        # calendarId defaults to "" and resolves against the empty-string key.
        assert formatted.calendar_name == "Empty Cal"


# ---------------------------------------------------------------------------
# _proxy error normalization
# ---------------------------------------------------------------------------


class TestProxy:
    async def test_passes_request_through_unchanged(self, mock_proxy):
        mock_proxy.return_value = {"raw": True}
        result = await _proxy(USER_ID, endpoint="/ep", method="GET", query={"q": "x"})
        assert result == {"raw": True}
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["user_id"] == USER_ID
        assert kwargs["toolkit"] == "GOOGLECALENDAR"
        assert kwargs["endpoint"] == "/ep"
        assert kwargs["method"] == "GET"
        assert kwargs["query"] == {"q": "x"}
        assert kwargs["body"] is None

    async def test_dumps_body_excluding_none(self, mock_proxy):
        mock_proxy.return_value = {}
        body = GoogleCalendarEventWrite(
            summary="s",
            description="d",
            start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00Z"),
            end=GoogleCalendarEventDateTime(date="2025-01-02"),
        )
        await _proxy(USER_ID, endpoint="/ep", method="POST", body=body)
        assert mock_proxy.call_args.kwargs["body"] == {
            "summary": "s",
            "description": "d",
            "start": {"dateTime": "2025-01-01T10:00:00Z"},
            "end": {"date": "2025-01-02"},
        }

    async def test_not_connected_becomes_structured_http_error(self, mock_proxy):
        error = AppError(
            message="No active GOOGLECALENDAR connection",
            status_code=403,
            meta={"error_code": INTEGRATION_NOT_CONNECTED, "toolkit": "GOOGLECALENDAR"},
        )
        mock_proxy.side_effect = error
        with pytest.raises(HTTPException) as exc:
            await _proxy(USER_ID, endpoint="/ep", method="GET")
        assert exc.value.status_code == 403
        assert exc.value.detail == {
            "type": "integration",
            "error_code": INTEGRATION_NOT_CONNECTED,
            "toolkit": "GOOGLECALENDAR",
            "message": "Reconnect Google Calendar to load your events.",
        }
        assert exc.value.__cause__ is error

    async def test_provider_error_message_wins(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500, {"error": {"message": "provider said no"}})
        with pytest.raises(HTTPException) as exc:
            await _proxy(USER_ID, endpoint="/ep", method="GET")
        assert exc.value.status_code == 500
        assert exc.value.detail == "provider said no"

    async def test_provider_error_without_message_keeps_generic_detail(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500, {"error": {}})
        with pytest.raises(HTTPException) as exc:
            await _proxy(USER_ID, endpoint="/ep", method="GET")
        assert exc.value.detail == "GOOGLECALENDAR API error (500)"

    async def test_non_dict_provider_response_keeps_generic_detail(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500, "raw string body")
        with pytest.raises(HTTPException) as exc:
            await _proxy(USER_ID, endpoint="/ep", method="GET")
        assert exc.value.detail == "GOOGLECALENDAR API error (500)"

    async def test_error_without_provider_response_keeps_message(self, mock_proxy):
        mock_proxy.side_effect = AppError(message="plain failure", status_code=502)
        with pytest.raises(HTTPException) as exc:
            await _proxy(USER_ID, endpoint="/ep", method="GET")
        assert exc.value.status_code == 502
        assert exc.value.detail == "plain failure"


# ---------------------------------------------------------------------------
# list_calendars / metadata
# ---------------------------------------------------------------------------


class TestListCalendars:
    async def test_returns_full_data(self, mock_proxy):
        items = [{"id": "cal-1", "summary": "Work", "description": "d", "backgroundColor": "#abc"}]
        mock_proxy.return_value = {"items": items}
        result = await list_calendars(USER_ID)
        assert [entry.id for entry in result.items] == ["cal-1"]
        assert result.items[0].summary == "Work"
        # Google's extra keys ride through untouched for the web client.
        assert result.items[0].model_dump() == items[0]
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["toolkit"] == "GOOGLECALENDAR"
        assert kwargs["endpoint"].endswith("/users/me/calendarList")
        assert kwargs["method"] == "GET"
        assert kwargs["user_id"] == USER_ID

    async def test_short_format_returns_subset(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [
                {
                    "id": "c1",
                    "summary": "A",
                    "description": "x",
                    "backgroundColor": "#1",
                    "etag": "drop-me",
                }
            ]
        }
        result = to_calendar_summaries(await list_calendars(USER_ID))
        assert [summary.model_dump() for summary in result] == [
            {"id": "c1", "summary": "A", "description": "x", "backgroundColor": "#1"}
        ]

    async def test_propagates_proxy_error_as_http_exception(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500, {"error": {"message": "boom"}})
        with pytest.raises(HTTPException) as exc:
            await list_calendars(USER_ID)
        assert exc.value.status_code == 500
        assert "boom" in str(exc.value.detail)


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
        assert mock_proxy.await_args.kwargs["user_id"] == USER_ID

    async def test_defaults_color_and_name(self, mock_proxy):
        mock_proxy.return_value = {"items": [{"id": "c1"}]}
        color_map, name_map = await get_calendar_metadata_map(USER_ID)
        assert color_map == {"c1": DEFAULT_CALENDAR_COLOR}
        assert name_map == {"c1": "Calendar"}

    async def test_skips_entries_without_id(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [
                {"id": ""},
                {"id": "c1", "summary": "Work", "backgroundColor": "#fff"},
            ]
        }
        color_map, name_map = await get_calendar_metadata_map(USER_ID)
        assert color_map == {"c1": "#fff"}
        assert name_map == {"c1": "Work"}


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
        assert kwargs["user_id"] == USER_ID
        assert kwargs["query"]["maxResults"] == 42
        assert kwargs["query"]["pageToken"] == "tk"
        assert kwargs["query"]["timeMin"] == "2025-01-01T00:00:00Z"
        assert kwargs["query"]["timeMax"] == "2025-01-02T00:00:00Z"
        assert kwargs["query"]["singleEvents"] == "true"

    async def test_defaults_query_when_optional_args_absent(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        await fetch_calendar_events("primary", USER_ID)
        assert mock_proxy.call_args.kwargs["query"] == {
            "maxResults": 20,
            "singleEvents": "true",
            "orderBy": "startTime",
        }


class TestFetchAllCalendarEvents:
    def _event(self) -> GoogleCalendarEventResource:
        return GoogleCalendarEventResource(
            id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )

    async def test_truncated_when_more_pages_exist_beyond_cap(self):
        """20 full pages, each with a next token: the loop hits the page cap
        with a pending token, so the calendar is truncated (events remain)."""
        event = self._event()
        pages = [
            GoogleCalendarEventsPage(items=[event], nextPageToken=f"tk{i}")
            for i in range(1, 21)
        ]
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_fetch.side_effect = pages
            result = await fetch_all_calendar_events("c1", USER_ID)
        assert mock_fetch.await_count == 20
        assert result.truncated is True
        assert result.total_fetched == 20
        mock_log.warning.assert_any_call(
            "Calendar truncated at events (hit max pages limit)",
            calendar_id="c1",
            all_items_count=20,
            user_id=USER_ID,
        )

    async def test_not_truncated_when_last_page_exhausts_token(self):
        """19 full pages plus a final page WITHOUT a next token: the loop exits
        at the page cap with nothing left to fetch, so the calendar is NOT
        truncated. The predicate is ``page_count >= max_pages AND token is not
        None`` — both must hold for truncation to be reported."""
        event = self._event()
        pages = [
            GoogleCalendarEventsPage(items=[event], nextPageToken=f"tk{i}")
            for i in range(1, 20)
        ] + [GoogleCalendarEventsPage(items=[event])]
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_fetch.side_effect = pages
            result = await fetch_all_calendar_events("c1", USER_ID)
        assert mock_fetch.await_count == 20
        assert result.truncated is False
        assert result.total_fetched == 20
        assert len(result.items) == 20
        mock_log.warning.assert_not_called()


class TestSearchEventsInCalendar:
    async def test_search_query_in_params(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        await search_events_in_calendar("primary", "lunch", USER_ID)
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["query"]["q"] == "lunch"
        assert kwargs["query"]["maxResults"] == 50

    async def test_exact_params_with_time_bounds(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        with patch("app.services.calendar_service.log") as mock_log:
            await search_events_in_calendar(
                "primary",
                "lunch",
                USER_ID,
                time_min="2025-01-01T00:00:00Z",
                time_max="2025-01-02T00:00:00Z",
            )
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["query"] == {
            "q": "lunch",
            "maxResults": 50,
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": "2025-01-01T00:00:00Z",
            "timeMax": "2025-01-02T00:00:00Z",
        }
        assert kwargs["user_id"] == USER_ID
        assert kwargs["endpoint"].endswith("/calendars/primary/events")
        assert kwargs["method"] == "GET"
        mock_log.info.assert_any_call(
            "Searching calendar",
            calendar_id="primary",
            time_min="2025-01-01T00:00:00Z",
            time_max="2025-01-02T00:00:00Z",
        )

    async def test_returns_parsed_page(self, mock_proxy):
        mock_proxy.return_value = {
            "items": [{"id": "e1", "start": {"dateTime": "2025-01-01T10:00:00"}}],
            "nextPageToken": "tk",
        }
        with patch("app.services.calendar_service.log") as mock_log:
            result = await search_events_in_calendar("primary", "lunch", USER_ID)
        assert result.items[0].id == "e1"
        assert result.nextPageToken == "tk"
        mock_log.info.assert_any_call(
            "Calendar search returned events", calendar_id="primary", event_count=1
        )

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
        assert result.id == "evt-1"
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

    async def test_exact_payload_shape(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="Sync",
            description="desc",
            start="2025-01-15T10:00:00",
            end="2025-01-15T11:00:00",
            timezone="America/New_York",
        )
        await create_calendar_event(event, USER_ID)
        assert mock_proxy.call_args.kwargs["body"] == {
            "summary": "Sync",
            "description": "desc",
            "start": {"dateTime": "2025-01-15T10:00:00Z", "timeZone": "America/New_York"},
            "end": {"dateTime": "2025-01-15T11:00:00Z", "timeZone": "America/New_York"},
        }

    async def test_uses_explicit_calendar_id(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="x",
            description="",
            start="2025-01-15T10:00:00",
            end="2025-01-15T11:00:00",
            calendar_id="cal-9",
        )
        with patch("app.services.calendar_service.log") as mock_log:
            await create_calendar_event(event, USER_ID)
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["endpoint"].endswith("/calendars/cal-9/events")
        assert kwargs["user_id"] == USER_ID
        mock_log.set.assert_called_once_with(
            calendar={
                "action": "create_event",
                "calendar_id": "cal-9",
                "summary": "x",
                "event_id": "evt",
            }
        )

    async def test_attendees_added_with_send_updates(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="x",
            description="",
            start="2025-01-15T10:00:00",
            end="2025-01-15T11:00:00",
            attendees=["a@b.com", "c@d.com"],
        )
        await create_calendar_event(event, USER_ID)
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["body"]["attendees"] == [{"email": "a@b.com"}, {"email": "c@d.com"}]
        assert kwargs["query"] == {"sendUpdates": "all"}

    async def test_no_optional_metadata_omits_query_and_body_keys(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="x", description="", start="2025-01-15T10:00:00", end="2025-01-15T11:00:00"
        )
        await create_calendar_event(event, USER_ID)
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["query"] is None
        assert "attendees" not in kwargs["body"]
        assert "conferenceData" not in kwargs["body"]

    async def test_recurrence_in_payload(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="x",
            description="",
            start="2025-01-15T10:00:00",
            end="2025-01-15T11:00:00",
            recurrence=RecurrenceData(rrule=RecurrenceRule(frequency="WEEKLY", by_day=["MO"])),
        )
        await create_calendar_event(event, USER_ID)
        body = mock_proxy.call_args.kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]
        assert body["start"]["timeZone"] == "UTC"

    async def test_meeting_room_request_id_shape(self, mock_proxy):
        mock_proxy.return_value = {"id": "evt"}
        event = EventCreateRequest(
            summary="Meet",
            description="",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
            create_meeting_room=True,
        )
        await create_calendar_event(event, USER_ID)
        request_id = mock_proxy.call_args.kwargs["body"]["conferenceData"]["createRequest"][
            "requestId"
        ]
        assert re.fullmatch(r"meet_\d+", request_id)


class TestDeleteCalendarEvent:
    async def test_deletes_event(self, mock_proxy):
        mock_proxy.return_value = None
        result = await delete_calendar_event(
            EventDeleteRequest(event_id="evt-1", calendar_id="primary"), USER_ID
        )
        assert result == EventDeleteResponse(success=True, message="Event deleted successfully")
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["method"] == "DELETE"
        assert kwargs["endpoint"].endswith("/calendars/primary/events/evt-1")
        assert kwargs["user_id"] == USER_ID

    async def test_defaults_to_primary_calendar(self, mock_proxy):
        mock_proxy.return_value = None
        await delete_calendar_event(EventDeleteRequest(event_id="evt-1"), USER_ID)
        assert mock_proxy.call_args.kwargs["endpoint"].endswith("/calendars/primary/events/evt-1")

    async def test_defaults_to_primary_when_calendar_id_falsy(self, mock_proxy):
        mock_proxy.return_value = None
        request = EventDeleteRequest(event_id="evt-1")
        request.calendar_id = None
        await delete_calendar_event(request, USER_ID)
        assert mock_proxy.call_args.kwargs["endpoint"].endswith("/calendars/primary/events/evt-1")

    async def test_404_raises_clean_message(self, mock_proxy):
        mock_proxy.side_effect = _http_error(404)
        with pytest.raises(HTTPException) as exc:
            await delete_calendar_event(
                EventDeleteRequest(event_id="x", calendar_id="primary"), USER_ID
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Event not found or already deleted"

    async def test_non_404_error_propagates(self, mock_proxy):
        mock_proxy.side_effect = _http_error(500, {"error": {"message": "boom"}})
        with pytest.raises(HTTPException) as exc:
            await delete_calendar_event(EventDeleteRequest(event_id="x"), USER_ID)
        assert exc.value.status_code == 500
        assert exc.value.detail == "boom"


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
        assert result.calendarId == "primary"
        # Two calls: GET existing + PUT update
        get_call = mock_proxy.call_args_list[0]
        assert get_call.kwargs["method"] == "GET"
        assert get_call.kwargs["user_id"] == USER_ID
        assert get_call.kwargs["endpoint"].endswith("/calendars/primary/events/evt")
        put_call = mock_proxy.call_args_list[1]
        assert put_call.kwargs["method"] == "PUT"
        assert put_call.kwargs["user_id"] == USER_ID
        assert put_call.kwargs["endpoint"] == get_call.kwargs["endpoint"]
        assert put_call.kwargs["body"]["summary"] == "New"

    async def test_defaults_to_primary_when_calendar_id_falsy(self, mock_proxy):
        mock_proxy.side_effect = [
            {"summary": "Old", "description": "d", "start": {}, "end": {}},
            {"id": "evt", "summary": "Old"},
        ]
        request = EventUpdateRequest(event_id="evt", summary="New")
        request.calendar_id = None
        await update_calendar_event(request, USER_ID)
        get_call = mock_proxy.call_args_list[0]
        assert get_call.kwargs["method"] == "GET"
        assert get_call.kwargs["endpoint"].endswith("/calendars/primary/events/evt")

    async def test_get_404_raises_clean_message(self, mock_proxy):
        mock_proxy.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await update_calendar_event(EventUpdateRequest(event_id="evt"), USER_ID)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Event not found or access denied"

    async def test_put_404_raises_clean_message(self, mock_proxy):
        mock_proxy.side_effect = [
            {"summary": "Old", "description": "d", "start": {}, "end": {}},
            HTTPException(status_code=404, detail="not found"),
        ]
        with pytest.raises(HTTPException) as exc:
            await update_calendar_event(EventUpdateRequest(event_id="evt", summary="New"), USER_ID)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Event not found or access denied"

    async def test_non_404_error_propagates(self, mock_proxy):
        mock_proxy.side_effect = HTTPException(status_code=500, detail="boom")
        with pytest.raises(HTTPException) as exc:
            await update_calendar_event(EventUpdateRequest(event_id="evt"), USER_ID)
        assert exc.value.status_code == 500
        assert exc.value.detail == "boom"

    async def test_merges_existing_summary_and_description(self, mock_proxy):
        mock_proxy.side_effect = [
            {"summary": "Old", "description": "d", "start": {}, "end": {}},
            {"id": "evt", "summary": "Old"},
        ]
        await update_calendar_event(
            EventUpdateRequest(event_id="evt", description="New desc"), USER_ID
        )
        body = mock_proxy.call_args_list[1].kwargs["body"]
        assert body["summary"] == "Old"
        assert body["description"] == "New desc"

    async def test_empty_existing_summary_and_description_fall_back_to_empty(self, mock_proxy):
        mock_proxy.side_effect = [
            {"summary": None, "description": None, "start": {}, "end": {}},
            {"id": "evt", "summary": ""},
        ]
        await update_calendar_event(EventUpdateRequest(event_id="evt"), USER_ID)
        body = mock_proxy.call_args_list[1].kwargs["body"]
        assert body["summary"] == ""
        assert body["description"] == ""

    async def test_untouched_bounds_kept_as_is(self, mock_proxy):
        mock_proxy.side_effect = [
            {
                "summary": "Old",
                "description": "d",
                "start": {"dateTime": "2025-01-01T09:00:00Z", "timeZone": "UTC"},
                "end": {"dateTime": "2025-01-01T10:00:00Z", "timeZone": "UTC"},
            },
            {"id": "evt", "summary": "Old"},
        ]
        await update_calendar_event(EventUpdateRequest(event_id="evt", summary="New"), USER_ID)
        body = mock_proxy.call_args_list[1].kwargs["body"]
        assert body["start"] == {"dateTime": "2025-01-01T09:00:00Z", "timeZone": "UTC"}
        assert body["end"] == {"dateTime": "2025-01-01T10:00:00Z", "timeZone": "UTC"}

    async def test_timed_bounds_merged(self, mock_proxy):
        mock_proxy.side_effect = [
            {
                "summary": "Old",
                "description": "d",
                "start": {"dateTime": "2025-01-01T09:00:00Z", "timeZone": "UTC"},
                "end": {"dateTime": "2025-01-01T10:00:00Z", "timeZone": "UTC"},
            },
            {"id": "evt", "summary": "Old"},
        ]
        await update_calendar_event(
            EventUpdateRequest(event_id="evt", start="2025-01-02T09:00:00"), USER_ID
        )
        body = mock_proxy.call_args_list[1].kwargs["body"]
        assert body["start"] == {"dateTime": "2025-01-02T09:00:00Z", "timeZone": "UTC"}
        assert body["end"] == {"dateTime": "2025-01-01T10:00:00Z", "timeZone": "UTC"}

    async def test_existing_all_day_bounds_merged(self, mock_proxy):
        mock_proxy.side_effect = [
            {
                "summary": "Old",
                "description": "d",
                "start": {"date": "2025-01-01"},
                "end": {"date": "2025-01-02"},
            },
            {"id": "evt", "summary": "Old"},
        ]
        await update_calendar_event(
            EventUpdateRequest(
                event_id="evt",
                start="2025-01-05T00:00:00",
                end="2025-01-06T00:00:00",
            ),
            USER_ID,
        )
        body = mock_proxy.call_args_list[1].kwargs["body"]
        assert body["start"] == {"date": "2025-01-05"}
        assert body["end"] == {"date": "2025-01-06"}

    async def test_timezone_offset_used_when_timezone_absent(self, mock_proxy):
        mock_proxy.side_effect = [
            {
                "summary": "Old",
                "description": "d",
                "start": {"dateTime": "2025-01-01T09:00:00Z", "timeZone": "UTC"},
                "end": {"dateTime": "2025-01-01T10:00:00Z", "timeZone": "UTC"},
            },
            {"id": "evt", "summary": "Old"},
        ]
        await update_calendar_event(
            EventUpdateRequest(
                event_id="evt", start="2025-01-02T09:00:00", timezone_offset="+05:30"
            ),
            USER_ID,
        )
        body = mock_proxy.call_args_list[1].kwargs["body"]
        assert body["start"] == {"dateTime": "2025-01-02T09:00:00Z", "timeZone": "+05:30"}

    async def test_recurrence_kept_from_existing_when_omitted(self, mock_proxy):
        mock_proxy.side_effect = [
            {
                "summary": "Old",
                "description": "d",
                "recurrence": ["RRULE:FREQ=DAILY"],
                "start": {},
                "end": {},
            },
            {"id": "evt", "summary": "Old"},
        ]
        await update_calendar_event(EventUpdateRequest(event_id="evt", summary="New"), USER_ID)
        body = mock_proxy.call_args_list[1].kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=DAILY"]

    async def test_recurrence_replaced_when_given(self, mock_proxy):
        mock_proxy.side_effect = [
            {
                "summary": "Old",
                "description": "d",
                "recurrence": ["RRULE:FREQ=DAILY"],
                "start": {},
                "end": {},
            },
            {"id": "evt", "summary": "Old"},
        ]
        await update_calendar_event(
            EventUpdateRequest(
                event_id="evt",
                summary="New",
                recurrence=RecurrenceData(rrule=RecurrenceRule(frequency="WEEKLY", by_day=["TU"])),
            ),
            USER_ID,
        )
        body = mock_proxy.call_args_list[1].kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]


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
            mock_fetch.return_value = GoogleCalendarEventsPage()
            result = await get_calendar_events(USER_ID)
        assert result.selected_calendars == ["c1"]

    async def test_seeds_preferences_when_missing(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        mock_calendar_repo.get_for_user.return_value = None
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = GoogleCalendarEventsPage()
            await get_calendar_events(USER_ID)
        mock_calendar_repo.set_selected_calendars.assert_awaited_once()

    async def test_explicit_selection_persisted(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = GoogleCalendarEventsPage()
            result = await get_calendar_events(USER_ID, selected_calendars=["c2"])
        assert result.selected_calendars == ["c2"]
        mock_calendar_repo.set_selected_calendars.assert_awaited_once_with(USER_ID, ["c2"])
        mock_calendar_repo.get_for_user.assert_not_awaited()
        mock_fetch.assert_awaited_once()
        assert mock_fetch.await_args.args == ("c2", USER_ID, None, None, None, 20)

    async def test_only_selected_calendars_fetched(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        mock_calendar_repo.get_for_user.return_value = _prefs(["c2"])
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = GoogleCalendarEventsPage()
            result = await get_calendar_events(
                USER_ID, time_min="2025-01-01T00:00:00Z", time_max="2025-01-31T00:00:00Z"
            )
        mock_fetch.assert_awaited_once()
        assert mock_fetch.await_args.args == (
            "c2",
            USER_ID,
            None,
            "2025-01-01T00:00:00Z",
            "2025-01-31T00:00:00Z",
            20,
        )
        assert mock_proxy.await_args.kwargs["user_id"] == USER_ID
        assert result.selected_calendars == ["c2"]
        assert result.has_more is False

    async def test_fetch_all_paginates_across_pages(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        e1 = GoogleCalendarEventResource(
            id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        e2 = GoogleCalendarEventResource(
            id="e2", start=GoogleCalendarEventDateTime(dateTime="2025-01-02T10:00:00")
        )
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.side_effect = [
                GoogleCalendarEventsPage(items=[e1], nextPageToken="tk1"),
                GoogleCalendarEventsPage(items=[e2]),
            ]
            result = await get_calendar_events(
                USER_ID,
                fetch_all=True,
                time_min="2025-01-01T00:00:00Z",
                time_max="2025-01-31T00:00:00Z",
            )
        assert result.has_more is False
        assert result.calendars_truncated == []
        assert [event.id for event in result.events] == ["e1", "e2"]
        assert result.events[0].calendarId == "c1"
        assert result.events[1].calendarId == "c1"
        assert mock_fetch.await_args_list[0].kwargs == {
            "calendar_id": "c1",
            "user_id": USER_ID,
            "page_token": None,
            "time_min": "2025-01-01T00:00:00Z",
            "time_max": "2025-01-31T00:00:00Z",
            "max_results": 250,
        }
        assert mock_fetch.await_args_list[1].kwargs == {
            "calendar_id": "c1",
            "user_id": USER_ID,
            "page_token": "tk1",
            "time_min": "2025-01-01T00:00:00Z",
            "time_max": "2025-01-31T00:00:00Z",
            "max_results": 250,
        }

    async def test_fetch_all_truncates_after_max_pages(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        event = GoogleCalendarEventResource(
            id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_fetch.return_value = GoogleCalendarEventsPage(items=[event], nextPageToken="tk")
            result = await get_calendar_events(USER_ID, fetch_all=True)
        assert mock_fetch.await_count == 20
        assert result.has_more is True
        assert result.calendars_truncated == ["c1"]
        assert len(result.events) == 20
        mock_log.info.assert_any_call(
            "Fetching ALL events for calendars in date range", selected_cal_objs_count=1
        )
        many_events_calls = [
            call
            for call in mock_log.info.call_args_list
            if call.args and call.args[0] == "Calendar has many events - fetched so far, page"
        ]
        assert len(many_events_calls) == 15
        mock_log.info.assert_any_call(
            "Calendar has many events - fetched so far, page",
            calendar_id="c1",
            all_items_count=6,
            page_count=6,
        )
        mock_log.warning.assert_any_call(
            "Calendar truncated at events (hit max pages limit)",
            calendar_id="c1",
            all_items_count=20,
            user_id=USER_ID,
        )
        mock_log.warning.assert_any_call(
            "Calendar was truncated", calendar_id="c1", user_id=USER_ID
        )
        mock_log.set.assert_called_once_with(
            calendar={
                "user_id": USER_ID,
                "calendars_queried": 1,
                "events_fetched": 20,
                "calendars_truncated": 1,
            }
        )
        mock_log.info.assert_any_call(
            "Fetched total events from calendars",
            all_events_count=20,
            selected_cal_objs_count=1,
        )

    async def test_max_results_none_triggers_fetch_all(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1"}]}
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = GoogleCalendarEventsPage()
            result = await get_calendar_events(USER_ID, max_results=None)
        assert result.has_more is False
        mock_fetch.assert_awaited_once_with(
            calendar_id="c1",
            user_id=USER_ID,
            page_token=None,
            time_min=None,
            time_max=None,
            max_results=250,
        )

    async def test_calendar_error_does_not_abort_fetch(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1", "c2"])
        e2 = GoogleCalendarEventResource(
            id="e2", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_fetch.side_effect = [AppError("boom"), GoogleCalendarEventsPage(items=[e2])]
            result = await get_calendar_events(USER_ID)
        assert [event.id for event in result.events] == ["e2"]
        assert result.events[0].calendarId == "c2"
        assert result.has_more is False
        assert result.selected_calendars == ["c1", "c2"]
        mock_log.error.assert_called_once_with(
            "Error fetching events for calendar",
            cal_id="c1",
            error="boom",
            error_type="AppError",
            user_id=USER_ID,
        )

    async def test_duplicate_events_keep_first_calendar_stamp(self, mock_proxy, mock_calendar_repo):
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1", "c2"])
        late = GoogleCalendarEventResource(
            id="dup", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T12:00:00")
        )
        early = GoogleCalendarEventResource(
            id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.side_effect = [
                GoogleCalendarEventsPage(items=[late]),
                GoogleCalendarEventsPage(items=[late, early]),
            ]
            result = await get_calendar_events(USER_ID)
        # The duplicate is carried into the result but is not re-stamped by the
        # second calendar — both copies keep the first calendar's source tag.
        assert [event.id for event in result.events] == ["e1", "dup", "dup"]
        assert result.events[0].calendarId == "c2"
        assert result.events[1].calendarId == "c1"
        assert result.events[2].calendarId == "c1"
        assert len(result.events) == 3


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
        assert len(result.events) == 1
        assert result.events[0].id == "e1"
        assert result.next_page_token == "tk"

    async def test_passes_pagination_and_bounds(self, mock_proxy):
        mock_proxy.return_value = {"items": []}
        with patch(
            "app.services.calendar_service.fetch_calendar_events", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = GoogleCalendarEventsPage()
            result = await get_calendar_events_by_id(
                "cal-7",
                USER_ID,
                page_token="tk",
                time_min="2025-01-01T00:00:00Z",
                time_max="2025-01-02T00:00:00Z",
            )
        assert result.events == []
        assert result.next_page_token is None
        mock_fetch.assert_awaited_once_with(
            "cal-7", USER_ID, "tk", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"
        )


class TestSearchCalendarEventsNative:
    async def test_searches_selected_calendars(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
            ) as mock_search,
        ):
            mock_search.return_value = GoogleCalendarEventsPage(
                items=[
                    GoogleCalendarEventResource(
                        id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00")
                    )
                ]
            )
            result = await search_calendar_events_native("foo", USER_ID)
        assert result.total_matches == 1
        assert result.total_events_searched == 1
        assert result.searched_calendars == ["Work"]
        assert result.matching_events[0].calendarId == "c1"
        assert result.matching_events[0].calendarTitle == "Work"
        mock_calendar_repo.get_for_user.assert_awaited_once_with(USER_ID)
        assert mock_proxy.await_args.kwargs["user_id"] == USER_ID
        mock_log.info.assert_any_call(
            "User has calendar preferences", user_selected_calendars=["c1"]
        )
        mock_log.info.assert_any_call("Searching selected calendars", calendar_count=1)
        mock_log.info.assert_any_call("Found events in calendar", event_count=1, calendar_id="c1")
        mock_log.info.assert_any_call(
            "Events remaining after filtering", filtered_event_count=1, calendar_id="c1"
        )
        mock_log.info.assert_any_call(
            "Total matching events across all calendars", all_matching_events_count=1
        )

    async def test_defaults_to_all_calendars_without_prefs(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = None
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}, {"id": "c2"}]}
        kept_c1 = GoogleCalendarEventResource(
            id="k1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        birthday = GoogleCalendarEventResource(
            id="b1", eventType="birthday", start=GoogleCalendarEventDateTime(date="2025-01-02")
        )
        kept_c2 = GoogleCalendarEventResource(
            id="k2", start=GoogleCalendarEventDateTime(dateTime="2025-01-02T10:00:00")
        )
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
            ) as mock_search,
        ):
            mock_search.side_effect = [
                GoogleCalendarEventsPage(items=[kept_c1, birthday]),
                GoogleCalendarEventsPage(items=[kept_c2]),
            ]
            result = await search_calendar_events_native(
                "foo", USER_ID, time_min="2025-01-01T00:00:00Z", time_max="2025-01-31T00:00:00Z"
            )
        assert result.query == "foo"
        assert result.total_matches == 2
        assert result.total_events_searched == 2
        assert result.searched_calendars == ["Work", ""]
        assert [event.id for event in result.matching_events] == ["k1", "k2"]
        assert result.matching_events[0].calendarId == "c1"
        assert result.matching_events[0].calendarTitle == "Work"
        assert result.matching_events[1].calendarId == "c2"
        assert result.matching_events[1].calendarTitle == ""
        assert mock_search.await_args_list[0].args == (
            "c1",
            "foo",
            USER_ID,
            "2025-01-01T00:00:00Z",
            "2025-01-31T00:00:00Z",
        )
        assert mock_search.await_args_list[1].args == (
            "c2",
            "foo",
            USER_ID,
            "2025-01-01T00:00:00Z",
            "2025-01-31T00:00:00Z",
        )
        assert mock_proxy.await_args.kwargs["user_id"] == USER_ID
        mock_log.info.assert_any_call(
            "No preferences found, defaulting to all calendars: calendars",
            user_selected_calendars_count=2,
        )
        mock_log.info.assert_any_call(
            "Total matching events across all calendars", all_matching_events_count=2
        )

    async def test_empty_prefs_defaults_to_all_calendars(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs([])
        mock_proxy.return_value = {"items": [{"id": "c1"}, {"id": "c2"}]}
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = GoogleCalendarEventsPage()
            result = await search_calendar_events_native("foo", USER_ID)
        assert mock_search.await_count == 2
        assert result.total_matches == 0
        assert result.total_events_searched == 0

    async def test_empty_selection_searches_all_calendars(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["missing-cal"])
        mock_proxy.return_value = {
            "items": [{"id": "c1", "summary": "Work"}, {"id": "c2", "summary": "Home"}]
        }
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
            ) as mock_search,
        ):
            mock_search.return_value = GoogleCalendarEventsPage()
            result = await search_calendar_events_native("foo", USER_ID)
        assert mock_search.await_count == 2
        assert mock_search.await_args_list[0].args == ("c1", "foo", USER_ID, None, None)
        assert result.searched_calendars == ["Work", "Home"]
        mock_log.info.assert_any_call(
            "No selected calendars found, searching all available calendars"
        )

    async def test_falls_back_to_all_calendars_when_selected_find_nothing(
        self, mock_proxy, mock_calendar_repo
    ):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        mock_proxy.return_value = {
            "items": [{"id": "c1", "summary": "Work"}, {"id": "c2"}, {"id": "c3"}]
        }
        hit_c2 = GoogleCalendarEventResource(
            id="h2", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        hit_c3 = GoogleCalendarEventResource(
            id="h3", start=GoogleCalendarEventDateTime(dateTime="2025-01-02T10:00:00")
        )
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
            ) as mock_search,
        ):
            mock_search.side_effect = [
                GoogleCalendarEventsPage(),
                RuntimeError("boom"),
                GoogleCalendarEventsPage(items=[hit_c2]),
                GoogleCalendarEventsPage(items=[hit_c3]),
            ]
            result = await search_calendar_events_native(
                "foo", USER_ID, time_min="2025-01-01T00:00:00Z", time_max="2025-01-31T00:00:00Z"
            )
        # First pass: c1. Fallback: c1 (errors), c2 and c3 (both contribute).
        assert mock_search.await_count == 4
        for call, expected_calendar_id in zip(
            mock_search.await_args_list, ["c1", "c1", "c2", "c3"]
        ):
            assert call.args == (
                expected_calendar_id,
                "foo",
                USER_ID,
                "2025-01-01T00:00:00Z",
                "2025-01-31T00:00:00Z",
            )
        assert result.total_matches == 2
        assert result.total_events_searched == 2
        assert result.matching_events[0].calendarId == "c2"
        assert result.matching_events[0].calendarTitle == ""
        assert result.matching_events[1].calendarId == "c3"
        assert result.matching_events[1].calendarTitle == ""
        # searched_calendars reports the first-pass selection, not the fallback set.
        assert result.searched_calendars == ["Work"]
        mock_log.info.assert_any_call(
            "No events found in selected calendars, searching all calendars..."
        )
        mock_log.info.assert_any_call("Found events in calendar", event_count=1, calendar_id="c2")
        # The summary log fires before the fallback pass, so it reports the
        # first-pass count (zero here), not the final match total.
        mock_log.info.assert_any_call(
            "Total matching events across all calendars", all_matching_events_count=0
        )
        mock_log.error.assert_called_once_with(
            "Error searching events in calendar",
            cal_id="c1",
            error="boom",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    async def test_error_in_one_calendar_continues(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = None
        mock_proxy.return_value = {
            "items": [{"id": "c1", "summary": "Work"}, {"id": "c2", "summary": "Home"}]
        }
        hit = GoogleCalendarEventResource(
            id="h1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        with (
            patch("app.services.calendar_service.log") as mock_log,
            patch(
                "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
            ) as mock_search,
        ):
            mock_search.side_effect = [RuntimeError("boom"), GoogleCalendarEventsPage(items=[hit])]
            result = await search_calendar_events_native("foo", USER_ID)
        assert result.total_matches == 1
        assert result.matching_events[0].calendarId == "c2"
        assert result.total_events_searched == 1
        mock_log.error.assert_called_once_with(
            "Error searching events in calendar",
            cal_id="c1",
            error="boom",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


# ---------------------------------------------------------------------------
# Preferences (repository-backed)
# ---------------------------------------------------------------------------


class TestPreferences:
    async def test_get_returns_selected_calendars(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        assert await get_user_calendar_preferences(USER_ID) == CalendarPreferencesResponse(
            selected_calendars=["c1"]
        )
        mock_calendar_repo.get_for_user.assert_awaited_once_with(USER_ID)

    async def test_get_returns_empty_selection(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs([])
        assert await get_user_calendar_preferences(USER_ID) == CalendarPreferencesResponse(
            selected_calendars=[]
        )

    async def test_get_raises_when_missing(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_user_calendar_preferences(USER_ID)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Calendar preferences not found"

    async def test_update_returns_success_message(self, mock_calendar_repo):
        mock_calendar_repo.set_selected_calendars.return_value = True
        assert await update_user_calendar_preferences(
            USER_ID, ["c1"]
        ) == CalendarPreferencesUpdateResponse(message="Calendar preferences updated successfully")

    async def test_update_no_change_message(self, mock_calendar_repo):
        mock_calendar_repo.set_selected_calendars.return_value = False
        assert await update_user_calendar_preferences(
            USER_ID, ["c1"]
        ) == CalendarPreferencesUpdateResponse(message="No changes made to calendar preferences")

    async def test_update_persists_exact_selection(self, mock_calendar_repo):
        mock_calendar_repo.set_selected_calendars.return_value = True
        result = await update_user_calendar_preferences(USER_ID, ["c1", "c2"])
        assert result.message == "Calendar preferences updated successfully"
        mock_calendar_repo.set_selected_calendars.assert_awaited_once_with(USER_ID, ["c1", "c2"])


# ---------------------------------------------------------------------------
# Private helpers (synchronous)
# ---------------------------------------------------------------------------


class TestWithUtcSuffix:
    def test_empty_stays_empty(self):
        assert _with_utc_suffix("") == ""

    def test_z_suffix_unchanged(self):
        assert _with_utc_suffix("2025-01-01T10:00:00Z") == "2025-01-01T10:00:00Z"

    def test_plus_offset_unchanged(self):
        assert _with_utc_suffix("2025-01-01T10:00:00+05:00") == "2025-01-01T10:00:00+05:00"

    def test_minus_offset_unchanged(self):
        assert _with_utc_suffix("2025-01-01T10:00:00-05:00") == "2025-01-01T10:00:00-05:00"

    def test_naive_timestamp_gets_z(self):
        assert _with_utc_suffix("2025-01-01T10:00:00") == "2025-01-01T10:00:00Z"


class TestDatePart:
    def test_splits_timestamp(self):
        assert _date_part("2025-01-15T10:30:00") == "2025-01-15"

    def test_bare_date_unchanged(self):
        assert _date_part("2025-01-15") == "2025-01-15"

    def test_timestamp_with_offset(self):
        assert _date_part("2025-01-15T10:30:00+05:00") == "2025-01-15"

    def test_empty(self):
        assert _date_part("") == ""

    def test_split_at_first_t_separator(self):
        # A malformed timestamp with a second "T" still yields the part before
        # the FIRST separator — the date half is pinned to the leftmost "T"
        # (a right-anchored split would return the whole tail instead).
        assert _date_part("2025-01-15TT10:00:00") == "2025-01-15"


class TestEventSortKey:
    def test_event_without_start_sorts_first(self):
        event = GoogleCalendarEventResource(id="no-start")
        assert _event_sort_key(event) == ""

    def test_date_only_used_when_no_date_time(self):
        event = GoogleCalendarEventResource(start=GoogleCalendarEventDateTime(date="2025-01-01"))
        assert _event_sort_key(event) == "2025-01-01"

    def test_empty_start_object_falls_back_to_empty(self):
        event = GoogleCalendarEventResource(start=GoogleCalendarEventDateTime())
        assert _event_sort_key(event) == ""

    def test_date_time_preferred(self):
        event = GoogleCalendarEventResource(
            start=GoogleCalendarEventDateTime(date="2025-01-01", dateTime="2025-01-01T10:00:00")
        )
        assert _event_sort_key(event) == "2025-01-01T10:00:00"


class TestAllDayBounds:
    def _event(self) -> EventCreateRequest:
        return EventCreateRequest(
            summary="x",
            description="",
            is_all_day=True,
            start="2025-01-15",
            end="2025-01-16",
        )

    def test_both_dates_used(self):
        start_obj, end_obj = _all_day_bounds(self._event())
        assert start_obj == GoogleCalendarEventDateTime(date="2025-01-15")
        assert end_obj == GoogleCalendarEventDateTime(date="2025-01-16")
        assert start_obj.dateTime is None
        assert end_obj.dateTime is None

    def test_end_defaults_to_next_day(self):
        event = self._event()
        event.end = None
        start_obj, end_obj = _all_day_bounds(event)
        assert start_obj.date == "2025-01-15"
        assert end_obj.date == "2025-01-16"

    def test_end_defaults_across_year_boundary(self):
        event = self._event()
        event.start = "2025-12-31"
        event.end = None
        start_obj, end_obj = _all_day_bounds(event)
        assert start_obj.date == "2025-12-31"
        assert end_obj.date == "2026-01-01"

    def test_start_with_time_component_uses_date_part(self):
        event = self._event()
        event.start = "2025-01-15T10:00:00"
        event.end = "2025-01-16T09:00:00"
        start_obj, end_obj = _all_day_bounds(event)
        assert start_obj.date == "2025-01-15"
        assert end_obj.date == "2025-01-16"

    def test_missing_start_uses_today(self):
        event = self._event()
        event.start = None
        event.end = None
        with patch("app.services.calendar_service.datetime") as fake_datetime:
            fake_datetime.now.return_value = datetime(2025, 6, 15, 12, 0, 0)
            start_obj, end_obj = _all_day_bounds(event)
        assert start_obj.date == "2025-06-15"
        assert end_obj.date == "2025-06-16"


class TestTimedBounds:
    def _event(self) -> EventCreateRequest:
        return EventCreateRequest(
            summary="x", description="", start="2025-01-15T10:00:00", end="2025-01-15T11:00:00"
        )

    def test_utc_default_timezone(self):
        start_obj, end_obj = _timed_bounds(self._event())
        assert start_obj == GoogleCalendarEventDateTime(
            dateTime="2025-01-15T10:00:00Z", timeZone="UTC"
        )
        assert end_obj == GoogleCalendarEventDateTime(
            dateTime="2025-01-15T11:00:00Z", timeZone="UTC"
        )

    def test_explicit_timezone(self):
        event = self._event()
        event.timezone = "America/New_York"
        start_obj, end_obj = _timed_bounds(event)
        assert start_obj.dateTime == "2025-01-15T10:00:00Z"
        assert start_obj.timeZone == "America/New_York"
        assert end_obj.dateTime == "2025-01-15T11:00:00Z"
        assert end_obj.timeZone == "America/New_York"

    def test_timestamp_with_offset_kept(self):
        event = self._event()
        event.start = "2025-01-15T10:00:00+05:00"
        event.end = "2025-01-15T11:00:00+05:00"
        start_obj, _ = _timed_bounds(event)
        assert start_obj.dateTime == "2025-01-15T10:00:00+05:00"

    def test_missing_start_raises(self):
        event = self._event()
        event.start = None
        with pytest.raises(HTTPException) as exc:
            _timed_bounds(event)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Start and end times are required for time-specific events"

    def test_missing_end_raises(self):
        event = self._event()
        event.end = None
        with pytest.raises(HTTPException) as exc:
            _timed_bounds(event)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Start and end times are required for time-specific events"

    def test_invalid_time_raises(self):
        event = self._event()
        event.start = 12345
        with pytest.raises(HTTPException) as exc:
            _timed_bounds(event)
        assert exc.value.status_code == 400
        assert "Invalid datetime format" in str(exc.value.detail)


class TestCreateRecurrenceRules:
    def _recurring_event(
        self, *, is_all_day: bool, timezone: str | None = None
    ) -> EventCreateRequest:
        return EventCreateRequest(
            summary="x",
            description="",
            is_all_day=is_all_day,
            start="2025-01-15" if is_all_day else "2025-01-15T10:00:00",
            end="2025-01-16" if is_all_day else "2025-01-15T11:00:00",
            timezone=timezone,
            recurrence=RecurrenceData(
                rrule=RecurrenceRule(frequency="WEEKLY", by_day=["MO", "WE"])
            ),
        )

    def test_no_recurrence_returns_none(self):
        event = EventCreateRequest(
            summary="x", description="", start="2025-01-15T10:00:00", end="2025-01-15T11:00:00"
        )
        assert (
            _create_recurrence_rules(
                event, GoogleCalendarEventDateTime(), GoogleCalendarEventDateTime()
            )
            is None
        )

    def test_timed_stamps_event_timezone(self):
        event = self._recurring_event(is_all_day=False, timezone="Europe/Paris")
        start_obj = GoogleCalendarEventDateTime(
            dateTime="2025-01-15T10:00:00", timeZone="America/LA"
        )
        end_obj = GoogleCalendarEventDateTime(dateTime="2025-01-15T11:00:00", timeZone="America/LA")
        rules = _create_recurrence_rules(event, start_obj, end_obj)
        assert rules == ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE"]
        assert start_obj.timeZone == "Europe/Paris"
        assert end_obj.timeZone == "Europe/Paris"

    def test_timed_without_timezone_uses_utc(self):
        event = self._recurring_event(is_all_day=False)
        start_obj = GoogleCalendarEventDateTime(dateTime="2025-01-15T10:00:00", timeZone="UTC")
        end_obj = GoogleCalendarEventDateTime(dateTime="2025-01-15T11:00:00", timeZone="UTC")
        _create_recurrence_rules(event, start_obj, end_obj)
        assert start_obj.timeZone == "UTC"
        assert end_obj.timeZone == "UTC"

    def test_all_day_leaves_timezone_untouched(self):
        event = self._recurring_event(is_all_day=True, timezone="UTC")
        start_obj = GoogleCalendarEventDateTime(date="2025-01-15", timeZone="America/LA")
        end_obj = GoogleCalendarEventDateTime(date="2025-01-16", timeZone="America/LA")
        rules = _create_recurrence_rules(event, start_obj, end_obj)
        assert rules == ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE"]
        assert start_obj.timeZone == "America/LA"
        assert end_obj.timeZone == "America/LA"

    def test_invalid_recurrence_raises(self):
        event = EventCreateRequest(
            summary="x", description="", start="2025-01-15T10:00:00", end="2025-01-15T11:00:00"
        )
        event.recurrence = _BadRecurrence()
        with pytest.raises(HTTPException) as exc:
            _create_recurrence_rules(
                event, GoogleCalendarEventDateTime(), GoogleCalendarEventDateTime()
            )
        assert exc.value.status_code == 400
        assert "Invalid recurrence rule format: boom" in str(exc.value.detail)


class TestUpdateRecurrenceRules:
    def _existing(self) -> GoogleCalendarEventResource:
        return GoogleCalendarEventResource(id="e", recurrence=["RRULE:FREQ=DAILY"])

    def test_omitted_recurrence_keeps_existing(self):
        event = EventUpdateRequest(event_id="e")
        assert _update_recurrence_rules(event, self._existing()) == ["RRULE:FREQ=DAILY"]

    def test_given_recurrence_replaces_existing(self):
        event = EventUpdateRequest(
            event_id="e", recurrence=RecurrenceData(rrule=RecurrenceRule(frequency="YEARLY"))
        )
        assert _update_recurrence_rules(event, self._existing()) == ["RRULE:FREQ=YEARLY"]

    def test_invalid_recurrence_raises(self):
        event = EventUpdateRequest(event_id="e")
        event.recurrence = _BadRecurrence()
        with patch("app.services.calendar_service.log") as mock_log:
            with pytest.raises(HTTPException) as exc:
                _update_recurrence_rules(event, self._existing())
        assert exc.value.status_code == 400
        assert "Invalid recurrence rule format: boom" in str(exc.value.detail)
        mock_log.error.assert_called_once_with(
            "Error processing recurrence rules", error="boom", error_type="ValueError"
        )


class TestMergeEventBounds:
    def _request(self) -> EventUpdateRequest:
        return EventUpdateRequest(event_id="e")

    def test_untouched_bounds_returned_unchanged(self):
        event = self._request()
        existing_start = GoogleCalendarEventDateTime(
            dateTime="2025-01-01T09:00:00Z", timeZone="UTC"
        )
        existing_end = GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00Z", timeZone="UTC")
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj is existing_start
        assert end_obj is existing_end

    def test_all_day_merge_with_dates(self):
        event = self._request()
        event.start = "2025-02-01T00:00:00"
        event.end = "2025-02-02T00:00:00"
        event.is_all_day = True
        start_obj, end_obj = _merge_event_bounds(
            event, GoogleCalendarEventDateTime(), GoogleCalendarEventDateTime()
        )
        assert start_obj == GoogleCalendarEventDateTime(date="2025-02-01")
        assert end_obj == GoogleCalendarEventDateTime(date="2025-02-02")

    def test_all_day_inferred_from_existing_date(self):
        event = self._request()
        event.start = "2025-02-01T00:00:00"
        existing_start = GoogleCalendarEventDateTime(date="2025-01-01")
        existing_end = GoogleCalendarEventDateTime(date="2025-01-02")
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj == GoogleCalendarEventDateTime(date="2025-02-01")
        assert end_obj == GoogleCalendarEventDateTime(date="2025-01-02")

    def test_all_day_existing_end_without_date(self):
        event = self._request()
        event.start = "2025-02-01"
        event.is_all_day = True
        existing_start = GoogleCalendarEventDateTime(date="2025-01-01")
        existing_end = GoogleCalendarEventDateTime()
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj.date == "2025-02-01"
        assert end_obj.date == ""

    def test_all_day_missing_fields_fall_back_to_empty_strings(self):
        event = self._request()
        event.is_all_day = True
        existing_start = GoogleCalendarEventDateTime()
        existing_end = GoogleCalendarEventDateTime()
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj.date == ""
        assert end_obj.date == ""

    def test_all_day_merge_from_existing_dates_when_start_absent(self):
        event = self._request()
        event.is_all_day = True
        existing_start = GoogleCalendarEventDateTime(date="2025-01-01")
        existing_end = GoogleCalendarEventDateTime(date="2025-01-02")
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj.date == "2025-01-01"
        assert end_obj.date == "2025-01-02"

    def test_timed_merge_uses_event_timezone(self):
        event = self._request()
        event.start = "2025-02-01T09:00:00"
        event.timezone = "Asia/Tokyo"
        existing_start = GoogleCalendarEventDateTime(
            dateTime="2025-01-01T09:00:00Z", timeZone="UTC"
        )
        existing_end = GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00Z", timeZone="UTC")
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj == GoogleCalendarEventDateTime(
            dateTime="2025-02-01T09:00:00Z", timeZone="Asia/Tokyo"
        )
        assert end_obj.dateTime == "2025-01-01T10:00:00Z"
        assert end_obj.timeZone == "Asia/Tokyo"

    def test_timed_merge_uses_timezone_offset(self):
        event = self._request()
        event.start = "2025-02-01T09:00:00"
        event.timezone_offset = "+05:30"
        existing_start = GoogleCalendarEventDateTime(
            dateTime="2025-01-01T09:00:00Z", timeZone="UTC"
        )
        existing_end = GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00Z", timeZone="UTC")
        start_obj, _ = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj.timeZone == "+05:30"

    def test_timed_merge_falls_back_to_existing_timezone(self):
        event = self._request()
        event.start = "2025-02-01T09:00:00"
        existing_start = GoogleCalendarEventDateTime(
            dateTime="2025-01-01T09:00:00Z", timeZone="UTC"
        )
        existing_end = GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00Z", timeZone="UTC")
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj.timeZone == "UTC"
        assert end_obj.timeZone == "UTC"

    def test_timed_merge_without_any_timezone(self):
        event = self._request()
        event.start = "2025-02-01T09:00:00"
        existing_start = GoogleCalendarEventDateTime(dateTime="2025-01-01T09:00:00Z")
        existing_end = GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00Z")
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj.timeZone is None
        assert end_obj.timeZone is None

    def test_timed_merge_missing_fields_fall_back_to_empty_strings(self):
        event = self._request()
        event.is_all_day = False
        existing_start = GoogleCalendarEventDateTime()
        existing_end = GoogleCalendarEventDateTime()
        start_obj, end_obj = _merge_event_bounds(event, existing_start, existing_end)
        assert start_obj.dateTime == ""
        assert end_obj.dateTime == ""
        assert start_obj.timeZone is None
        assert end_obj.timeZone is None

    def test_timed_merge_invalid_start_raises(self):
        event = self._request()
        event.start = 12345
        with pytest.raises(HTTPException) as exc:
            _merge_event_bounds(event, GoogleCalendarEventDateTime(), GoogleCalendarEventDateTime())
        assert exc.value.status_code == 400
        assert "Invalid datetime format" in str(exc.value.detail)


class TestResolveSelectedCalendars:
    def _cals(self) -> list[GoogleCalendarListEntry]:
        return [
            GoogleCalendarListEntry(id="c1", summary="Work"),
            GoogleCalendarListEntry(id="c2", summary="Home"),
        ]

    async def test_explicit_selection_persisted(self, mock_calendar_repo):
        result = await _resolve_selected_calendars(USER_ID, self._cals(), ["c2"])
        assert result == ["c2"]
        mock_calendar_repo.set_selected_calendars.assert_awaited_once_with(USER_ID, ["c2"])
        mock_calendar_repo.get_for_user.assert_not_awaited()

    async def test_stored_preferences_win(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        result = await _resolve_selected_calendars(USER_ID, self._cals(), None)
        assert result == ["c1"]
        mock_calendar_repo.get_for_user.assert_awaited_once_with(USER_ID)
        mock_calendar_repo.set_selected_calendars.assert_not_awaited()

    async def test_empty_stored_preferences_fall_back_to_all(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs([])
        result = await _resolve_selected_calendars(USER_ID, self._cals(), None)
        assert result == ["c1", "c2"]
        mock_calendar_repo.set_selected_calendars.assert_awaited_once_with(USER_ID, ["c1", "c2"])

    async def test_no_preferences_seeds_all(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = None
        result = await _resolve_selected_calendars(USER_ID, self._cals(), None)
        assert result == ["c1", "c2"]
        mock_calendar_repo.set_selected_calendars.assert_awaited_once_with(USER_ID, ["c1", "c2"])


class TestTagWithSourceCalendar:
    def _cal(self) -> GoogleCalendarListEntry:
        return GoogleCalendarListEntry(id="c1", summary="Work")

    def test_stamps_and_filters(self):
        cal = self._cal()
        kept = GoogleCalendarEventResource(
            id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        birthday = GoogleCalendarEventResource(
            id="b1", eventType="birthday", start=GoogleCalendarEventDateTime(date="2025-01-02")
        )
        result = _tag_with_source_calendar([kept, birthday], cal, set())
        assert [event.id for event in result] == ["e1"]
        assert result[0].calendarId == "c1"
        assert result[0].calendarTitle == "Work"
        # The birthday is stamped too, before being filtered out.
        assert birthday.calendarId == "c1"

    def test_seen_event_not_re_stamped(self):
        cal = self._cal()
        event = GoogleCalendarEventResource(
            id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        seen = {"e1"}
        result = _tag_with_source_calendar([event], cal, seen)
        # Still returned (filtering is unrelated to the seen set), but the
        # already-seen id is left without a stamp from this calendar.
        assert len(result) == 1
        assert result[0].id == "e1"
        assert result[0].calendarId is None
        assert result[0].calendarTitle is None

    def test_event_without_id_still_stamped(self):
        cal = GoogleCalendarListEntry(id="c1")
        event = GoogleCalendarEventResource(
            start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00:00")
        )
        result = _tag_with_source_calendar([event], cal, set())
        assert len(result) == 1
        assert result[0].calendarId == "c1"
        assert result[0].calendarTitle == ""
