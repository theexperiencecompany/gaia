"""Unit tests for the calendar service (app/services/calendar_service.py).

Every Google Calendar API call routes through the async Composio
``proxy_request``; preferences go through ``calendar_repository``. Tests mock
those two seams and assert the shape of each request. Pure helpers
(``filter_events``/``format_event_for_frontend``) stay synchronous.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
import pytest

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
    GoogleCalendarListEntry,
    RecurrenceData,
    RecurrenceRule,
)
from app.services.calendar_service import (
    _all_day_bounds,
    _selected_search_calendars,
    create_calendar_event,
    delete_calendar_event,
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


class TestSelectedSearchCalendars:
    async def test_preferences_matching_no_listed_calendar_search_everything(
        self, mock_calendar_repo: AsyncMock
    ):
        """Stored selections that reference calendars absent from Google's list
        would otherwise search nothing — the fallback covers every calendar."""
        mock_calendar_repo.get_for_user.return_value = _prefs(["deleted-cal"])
        calendars = [
            GoogleCalendarListEntry(id="cal-a", summary="A"),
            GoogleCalendarListEntry(id="cal-b", summary="B"),
        ]

        result = await _selected_search_calendars(USER_ID, calendars)

        assert result == calendars


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


class _UTCOnlyDateTime(datetime):
    """datetime stand-in whose local-time read lands on the previous day, so a
    non-UTC clock in production code shows up as a wrong date, not a flake."""

    @classmethod
    def now(cls, tz: datetime | None = None) -> datetime:  # type: ignore[override]  # mirrors datetime.now's optional-tz signature deliberately
        if tz is None:
            return cls(2026, 6, 14, 20, 0)  # naive local read: previous day
        return cls(2026, 6, 15, 2, 0, tzinfo=UTC)


class TestAllDayBounds:
    """The all-day defaulting rules: explicit bounds pass through, a missing end
    becomes the next day, and a missing start defaults to today (UTC)."""

    def test_a_start_with_no_end_ends_the_next_day(self) -> None:
        # The Pydantic model requires both fields; the service still defends the
        # partial shapes, so mutate after construction like the timed-event test.
        event = EventCreateRequest(
            summary="Trip", description="", start="2026-06-15", end="2026-06-20"
        )
        event.end = ""

        start, end = _all_day_bounds(event)

        assert start == GoogleCalendarEventDateTime(date="2026-06-15")
        assert end == GoogleCalendarEventDateTime(date="2026-06-16")

    @patch("app.services.calendar_service.datetime", _UTCOnlyDateTime)
    def test_a_missing_start_defaults_to_today_on_the_utc_calendar(self) -> None:
        """Google's end date is exclusive; the default must follow the UTC
        calendar — the fake clock's local read is the previous day."""
        event = EventCreateRequest(
            summary="Today",
            description="",
            start="2026-06-15",
            end="2026-06-16",
        )
        event.start = None
        event.end = None

        start, end = _all_day_bounds(event)

        assert start == GoogleCalendarEventDateTime(date="2026-06-15")
        assert end == GoogleCalendarEventDateTime(date="2026-06-16")


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

    @patch("app.services.calendar_service.datetime", _UTCOnlyDateTime)
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
        # The request id is a uniqueness token minted from the UTC clock — the
        # fake clock pins it exactly (a local-time read lands 6h+ off).
        assert (
            kwargs["body"]["conferenceData"]["createRequest"]["requestId"]
            == f"meet_{int(datetime(2026, 6, 15, 2, 0, tzinfo=UTC).timestamp())}"
        )

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

    @pytest.mark.parametrize("missing", ["start", "end"])
    async def test_missing_single_bound_for_timed_event_raises(self, mock_proxy, missing):
        """Both bounds are required individually — dropping either check lets a
        half-bounded timed event reach Google."""
        event = EventCreateRequest(
            summary="x",
            description="",
            is_all_day=False,
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
        )
        setattr(event, missing, None)
        with pytest.raises(HTTPException) as exc:
            await create_calendar_event(event, USER_ID)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Start and end times are required for time-specific events"
        mock_proxy.assert_not_awaited()

    async def test_invalid_timezone_for_timed_event_raises(self, mock_proxy):
        """A timezone that fails GoogleCalendarEventDateTime validation surfaces
        as a 400 'Invalid datetime format' error."""
        event = EventCreateRequest(
            summary="x",
            description="",
            is_all_day=False,
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
        )
        event.timezone = 123  # type-invalid value; set post-construction like above
        with pytest.raises(HTTPException) as exc:
            await create_calendar_event(event, USER_ID)
        assert exc.value.status_code == 400
        assert str(exc.value.detail).startswith("Invalid datetime format:")
        mock_proxy.assert_not_awaited()

    async def test_failing_recurrence_conversion_raises_400(self, mock_proxy):
        event = EventCreateRequest(
            summary="x",
            description="",
            is_all_day=False,
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
            recurrence=RecurrenceData(rrule=RecurrenceRule(frequency="DAILY")),
        )
        recurrence = Mock(spec=["to_google_calendar_format"])
        recurrence.to_google_calendar_format.side_effect = ValueError("boom")
        event.recurrence = recurrence
        with pytest.raises(HTTPException) as exc:
            await create_calendar_event(event, USER_ID)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Invalid recurrence rule format: boom"
        mock_proxy.assert_not_awaited()


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

    async def test_404_raises_clean_message(self, mock_proxy):
        mock_proxy.side_effect = _http_error(404)
        with pytest.raises(HTTPException) as exc:
            await delete_calendar_event(
                EventDeleteRequest(event_id="x", calendar_id="primary"), USER_ID
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Event not found or already deleted"

    async def test_percent_encodes_calendar_id_with_reserved_chars(self, mock_proxy):
        """Google calendar IDs like 'user@group.calendar.google.com' or
        '#contacts@group.v.calendar.google.com' contain '@'/'#'. Unencoded,
        those characters break the URL path (404s or a truncated path)."""
        mock_proxy.return_value = None
        await delete_calendar_event(
            EventDeleteRequest(
                event_id="evt-1", calendar_id="#contacts@group.v.calendar.google.com"
            ),
            USER_ID,
        )
        endpoint = mock_proxy.call_args.kwargs["endpoint"]
        assert "#contacts@group.v.calendar.google.com" not in endpoint
        assert endpoint.endswith(
            "/calendars/%23contacts%40group.v.calendar.google.com/events/evt-1"
        )


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
        assert mock_proxy.call_args_list[0].kwargs["method"] == "GET"
        assert mock_proxy.call_args_list[1].kwargs["method"] == "PUT"
        assert mock_proxy.call_args_list[1].kwargs["body"]["summary"] == "New"

    async def test_percent_encodes_calendar_id_with_reserved_chars(self, mock_proxy):
        """Same bug as delete_calendar_event: the GET-existing + PUT-update
        endpoint interpolates calendar_id/event_id unencoded."""
        mock_proxy.side_effect = [
            {"summary": "Old", "description": "d", "start": {}, "end": {}},
            {"id": "evt", "summary": "New"},
        ]
        await update_calendar_event(
            EventUpdateRequest(
                event_id="evt",
                calendar_id="user@group.calendar.google.com",
                summary="New",
            ),
            USER_ID,
        )
        get_endpoint = mock_proxy.call_args_list[0].kwargs["endpoint"]
        assert "user@group.calendar.google.com" not in get_endpoint
        assert get_endpoint.endswith("/calendars/user%40group.calendar.google.com/events/evt")

    async def test_get_404_raises_not_found_detail(self, mock_proxy):
        mock_proxy.side_effect = _http_error(404)
        with pytest.raises(HTTPException) as exc:
            await update_calendar_event(
                EventUpdateRequest(event_id="gone", calendar_id="primary", summary="New"),
                USER_ID,
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Event not found or access denied"
        assert mock_proxy.await_count == 1

    async def test_put_404_raises_not_found_detail(self, mock_proxy):
        mock_proxy.side_effect = [
            {"summary": "Old", "description": "d", "start": {}, "end": {}},
            _http_error(404),
        ]
        with pytest.raises(HTTPException) as exc:
            await update_calendar_event(
                EventUpdateRequest(event_id="evt", calendar_id="primary", summary="New"),
                USER_ID,
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Event not found or access denied"
        assert [call.kwargs["method"] for call in mock_proxy.call_args_list] == ["GET", "PUT"]

    async def test_failing_recurrence_conversion_logs_and_raises_400(self, mock_proxy):
        existing = {
            "summary": "Old",
            "description": "d",
            "start": {"dateTime": "2025-01-10T09:00:00Z"},
            "end": {"dateTime": "2025-01-10T10:00:00Z"},
        }
        mock_proxy.side_effect = [existing]
        request = EventUpdateRequest(event_id="evt", calendar_id="primary")
        recurrence = Mock(spec=["to_google_calendar_format"])
        recurrence.to_google_calendar_format.side_effect = ValueError("bad rule")
        request.recurrence = recurrence
        with (
            patch("app.services.calendar_service.log") as mock_log,
            pytest.raises(HTTPException) as exc,
        ):
            await update_calendar_event(request, USER_ID)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Invalid recurrence rule format: bad rule"
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["error_type"] == "ValueError"
        mock_proxy.assert_awaited_once()

    async def test_invalid_timezone_offset_in_update_raises_400(self, mock_proxy):
        """A bad timezone on a timed update surfaces as a 400 before any write."""
        mock_proxy.side_effect = [
            {
                "summary": "Old",
                "description": "d",
                "start": {"dateTime": "2025-01-10T09:00:00Z"},
                "end": {"dateTime": "2025-01-10T10:00:00Z"},
            },
        ]
        request = EventUpdateRequest(
            event_id="evt",
            calendar_id="primary",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
        )
        request.timezone_offset = 123  # type-invalid value; set post-construction
        with pytest.raises(HTTPException) as exc:
            await update_calendar_event(request, USER_ID)
        assert exc.value.status_code == 400
        assert str(exc.value.detail).startswith("Invalid datetime format:")
        assert [call.kwargs["method"] for call in mock_proxy.call_args_list] == ["GET"]


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


class TestSearchCalendarEventsNative:
    async def test_searches_selected_calendars(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = GoogleCalendarEventsPage(
                items=[
                    GoogleCalendarEventResource(
                        id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00")
                    )
                ]
            )
            result = await search_calendar_events_native("foo", USER_ID)
        assert result.total_matches == 1


# ---------------------------------------------------------------------------
# Preferences (repository-backed)
# ---------------------------------------------------------------------------


class TestPreferences:
    async def test_get_returns_selected_calendars(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        assert await get_user_calendar_preferences(USER_ID) == CalendarPreferencesResponse(
            selected_calendars=["c1"]
        )

    async def test_get_raises_when_missing(self, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_user_calendar_preferences(USER_ID)
        assert exc.value.status_code == 404

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


# ---------------------------------------------------------------------------
# Exact-behavior pins for the native search + delete paths
# ---------------------------------------------------------------------------


class TestSearchCalendarEventsNativePins:
    async def test_result_fields_are_exact(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = GoogleCalendarEventsPage(items=[])
            result = await search_calendar_events_native(
                "foo", USER_ID, time_min="2025-01-01", time_max="2025-02-01"
            )
        assert result.query == "foo"
        assert result.matching_events == []
        assert result.total_matches == 0
        assert result.total_events_searched == 0
        assert result.searched_calendars == ["Work"]
        # time bounds are forwarded to every per-calendar search
        search_kwargs = mock_search.await_args.kwargs
        assert search_kwargs["time_min"] == "2025-01-01"
        assert search_kwargs["time_max"] == "2025-02-01"

    async def test_empty_selected_search_falls_back_to_all_calendars(
        self, mock_proxy, mock_calendar_repo
    ):
        # Preferences select c1, but c1 yields nothing → all calendars searched.
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        mock_proxy.return_value = {
            "items": [
                {"id": "c1", "summary": "Work"},
                {"id": "c2", "summary": "Home"},
            ]
        }
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = GoogleCalendarEventsPage(items=[])
            result = await search_calendar_events_native("foo", USER_ID)

        searched_ids = [call.args[0] for call in mock_search.await_args_list]
        assert searched_ids == ["c1", "c2"]  # fallback covered c2 too
        assert result.searched_calendars == ["Work"]

    async def test_hits_are_tagged_with_their_source_calendar(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        event = GoogleCalendarEventResource(
            id="e1", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00")
        )
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = GoogleCalendarEventsPage(items=[event])
            result = await search_calendar_events_native("foo", USER_ID)

        assert result.total_matches == 1
        assert result.matching_events[0].calendarId == "c1"
        assert result.matching_events[0].calendarTitle == "Work"

    async def test_a_failing_calendar_is_skipped_not_fatal(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = None  # all calendars selected
        mock_proxy.return_value = {
            "items": [
                {"id": "c1", "summary": "Work"},
                {"id": "c2", "summary": "Home"},
            ]
        }
        good = GoogleCalendarEventResource(
            id="e2", start=GoogleCalendarEventDateTime(dateTime="2025-01-01T10:00")
        )
        responses = [RuntimeError("c1 exploded")]

        async def search(cal_id: str, *args: Any, **kwargs: Any) -> GoogleCalendarEventsPage:
            if isinstance(responses[0], Exception) and cal_id == "c1":
                raise responses[0]
            return GoogleCalendarEventsPage(items=[good] if cal_id == "c2" else [])

        with patch("app.services.calendar_service.search_events_in_calendar", side_effect=search):
            result = await search_calendar_events_native("foo", USER_ID)

        assert result.total_matches == 1
        assert result.matching_events[0].calendarId == "c2"
        assert result.searched_calendars == ["Work", "Home"]

    async def test_no_preferences_searches_every_calendar(self, mock_proxy, mock_calendar_repo):
        mock_calendar_repo.get_for_user.return_value = None
        mock_proxy.return_value = {
            "items": [
                {"id": "c1", "summary": "Work"},
                {"id": "c2", "summary": ""},
            ]
        }
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = GoogleCalendarEventsPage(items=[])
            result = await search_calendar_events_native("foo", USER_ID)

        assert [call.args[0] for call in mock_search.await_args_list] == ["c1", "c2"]
        # A calendar without a summary contributes an empty string, not None.
        assert result.searched_calendars == ["Work", ""]


class TestSearchArgumentPropagation:
    """Every search input must arrive intact at each seam: the preference
    lookup, the calendar listing, and both per-calendar search passes."""

    async def test_first_pass_forwards_user_query_and_bounds_exactly(
        self, mock_proxy, mock_calendar_repo
    ):
        mock_calendar_repo.get_for_user.return_value = None
        mock_proxy.return_value = {"items": [{"id": "c1", "summary": "Work"}]}
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = GoogleCalendarEventsPage(items=[])
            await search_calendar_events_native(
                "lunch", USER_ID, time_min="2025-01-01", time_max="2025-02-01"
            )

        # Preference lookup is keyed by the requesting user.
        mock_calendar_repo.get_for_user.assert_awaited_once_with(USER_ID)
        # The calendar listing ran for the requesting user.
        assert mock_proxy.call_args.kwargs["user_id"] == USER_ID
        # The per-calendar search got every argument, positionally intact.
        assert mock_search.await_args.args == ("c1", "lunch", USER_ID)
        assert mock_search.await_args.kwargs == {
            "time_min": "2025-01-01",
            "time_max": "2025-02-01",
        }

    async def test_fallback_pass_forwards_user_query_and_bounds_exactly(
        self, mock_proxy, mock_calendar_repo
    ):
        mock_calendar_repo.get_for_user.return_value = _prefs(["c1"])
        mock_proxy.return_value = {
            "items": [
                {"id": "c1", "summary": "Work"},
                {"id": "c2", "summary": "Home"},
            ]
        }
        with patch(
            "app.services.calendar_service.search_events_in_calendar", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = GoogleCalendarEventsPage(items=[])
            await search_calendar_events_native(
                "lunch", USER_ID, time_min="2025-01-01", time_max="2025-02-01"
            )

        assert len(mock_search.await_args_list) == 2
        fallback_call = mock_search.await_args_list[1]
        assert fallback_call.args == ("c2", "lunch", USER_ID)
        assert fallback_call.kwargs == {"time_min": "2025-01-01", "time_max": "2025-02-01"}


class TestDeleteCalendarEventPins:
    async def test_missing_calendar_id_defaults_to_primary(self, mock_proxy):
        mock_proxy.return_value = {}
        # Omitted calendar id: the model defaults it to "primary".
        request = EventDeleteRequest(event_id="evt1")
        result = await delete_calendar_event(request, USER_ID)
        assert result.success is True
        assert result.message == "Event deleted successfully"
        kwargs = mock_proxy.await_args.kwargs
        assert kwargs["endpoint"].endswith("/calendars/primary/events/evt1")
        assert kwargs["method"] == "DELETE"

    async def test_given_calendar_id_is_used(self, mock_proxy):
        mock_proxy.return_value = {}
        request = EventDeleteRequest(event_id="evt1", calendar_id="cal-9")
        await delete_calendar_event(request, USER_ID)
        assert mock_proxy.await_args.kwargs["endpoint"].endswith("/calendars/cal-9/events/evt1")
