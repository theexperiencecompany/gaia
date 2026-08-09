"""Unit tests for calendar API endpoints.

Tests the calendar endpoints with mocked service layer and integration
dependency to verify routing, status codes, response bodies, service-call
arguments, and validation.

All calendar endpoints use ``require_integration("calendar")`` which calls
``check_integration_status`` under the hood.  We patch that function to
return ``True`` so the authenticated ``client`` fixture from conftest.py
can reach the endpoint logic.  ``log`` is patched so the wide-event calls
each handler emits are asserted exactly, and the service seams are patched
so every handler's arguments and returned shapes are pinned.
"""

from typing import ClassVar
from unittest.mock import AsyncMock, call, patch

from httpx import AsyncClient

from app.models.calendar_models import (
    CalendarEventPageResponse,
    CalendarEventsResponse,
    CalendarListResponse,
    CalendarPreferencesResponse,
    CalendarPreferencesUpdateResponse,
    EventCreateRequest,
    EventDeleteRequest,
    EventDeleteResponse,
    EventUpdateRequest,
    GoogleCalendarEventResource,
    GoogleCalendarListEntry,
)
from tests.conftest import FAKE_USER

API = "/api/v1"
USER_ID = FAKE_USER["user_id"]

# All calendar endpoints go through require_integration("calendar") which
# calls check_integration_status.  We patch it globally for this module so
# every request reaches the actual endpoint handler.
INTEGRATION_PATCH = "app.api.v1.dependencies.google_scope_dependencies.check_integration_status"
LOG_PATCH = "app.api.v1.endpoints.calendar.log"
SVC_PATCH = "app.api.v1.endpoints.calendar.calendar_service"
DELETE_PATCH = "app.api.v1.endpoints.calendar.delete_calendar_event"
UPDATE_PATCH = "app.api.v1.endpoints.calendar.update_calendar_event"

# The endpoint parses YYYY-MM-DD into an ISO string with a UTC tzinfo; an
# end_date is exclusive, so one day is added to the parsed bound.
START_ISO = "2026-03-01T00:00:00+00:00"
END_EXCLUSIVE_ISO = "2026-04-01T00:00:00+00:00"

# 2026-02-31 is not a real date: the GET endpoints' strptime path rejects it.
INVALID_DATE = "2026-02-31"
START_DATE_ERROR = "Invalid start_date format. Use YYYY-MM-DD"
END_DATE_ERROR = "Invalid end_date format. Use YYYY-MM-DD"


def create_event_model(summary: str, start: str, end: str) -> EventCreateRequest:
    """The EventCreateRequest the endpoint hands to the service for a payload."""
    return EventCreateRequest(summary=summary, start=start, end=end)


def update_event_model(event_id: str, summary: str) -> EventUpdateRequest:
    """The EventUpdateRequest the endpoint hands to the service for a payload."""
    return EventUpdateRequest(event_id=event_id, summary=summary)


def delete_event_model(event_id: str, calendar_id: str = "primary") -> EventDeleteRequest:
    """The EventDeleteRequest the endpoint hands to the service for a payload."""
    return EventDeleteRequest(event_id=event_id, calendar_id=calendar_id)


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/list
# ---------------------------------------------------------------------------


class TestGetCalendarList:
    """GET /api/v1/calendar/list"""

    async def test_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.list_calendars.return_value = CalendarListResponse(
                items=[GoogleCalendarListEntry(id="primary", summary="Main Calendar")]
            )
            resp = await client.get(f"{API}/calendar/list")
        assert resp.status_code == 200
        assert resp.json() == {"items": [{"id": "primary", "summary": "Main Calendar"}]}
        mock_svc.list_calendars.assert_awaited_once_with(USER_ID)
        mock_log.set.assert_any_call(user={"id": USER_ID}, calendar={"operation": "list_calendars"})
        mock_log.set.assert_any_call(calendar={"operation": "list_calendars", "event_count": 1})

    async def test_service_error_returns_500_with_detail(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.list_calendars.side_effect = Exception("boom")
            resp = await client.get(f"{API}/calendar/list")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "boom"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/list")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/events/query
# ---------------------------------------------------------------------------


class TestQueryEvents:
    """POST /api/v1/calendar/events/query"""

    async def test_query_events_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[GoogleCalendarEventResource(id="ev1", summary="Meeting")],
                selected_calendars=["primary"],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.post(
                f"{API}/calendar/events/query",
                json={
                    "selected_calendars": ["primary"],
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-31",
                    "max_results": 50,
                    "fetch_all": False,
                },
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "events": [{"id": "ev1", "summary": "Meeting"}],
            "selectedCalendars": ["primary"],
            "has_more": False,
            "calendars_truncated": [],
        }
        mock_svc.get_calendar_events.assert_awaited_once_with(
            user_id=USER_ID,
            selected_calendars=["primary"],
            time_min=START_ISO,
            time_max=END_EXCLUSIVE_ISO,
            max_results=50,
            fetch_all=False,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": 31,
            },
        )
        mock_log.set.assert_any_call(calendar={"operation": "get_events", "event_count": 1})

    async def test_query_events_without_dates(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=["primary"],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.post(
                f"{API}/calendar/events/query",
                json={"selected_calendars": ["primary"]},
            )
        assert resp.status_code == 200
        mock_svc.get_calendar_events.assert_awaited_once_with(
            user_id=USER_ID,
            selected_calendars=["primary"],
            time_min=None,
            time_max=None,
            max_results=None,
            fetch_all=True,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": None,
            },
        )

    async def test_query_events_rejects_bad_date_format(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True):
            resp = await client.post(
                f"{API}/calendar/events/query",
                json={
                    "selected_calendars": ["primary"],
                    "start_date": "03-01-2026",
                },
            )
        assert resp.status_code == 422

    async def test_query_events_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.side_effect = Exception("API down")
            resp = await client.post(
                f"{API}/calendar/events/query",
                json={"selected_calendars": ["primary"]},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "API down"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/calendar/events/query",
            json={"selected_calendars": ["primary"]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/events
# ---------------------------------------------------------------------------


class TestGetEvents:
    """GET /api/v1/calendar/events"""

    async def test_get_events_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=[],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.get(f"{API}/calendar/events")
        assert resp.status_code == 200
        assert resp.json() == {
            "events": [],
            "selectedCalendars": [],
            "has_more": False,
            "calendars_truncated": [],
        }
        mock_svc.get_calendar_events.assert_awaited_once_with(
            user_id=USER_ID,
            selected_calendars=None,
            time_min=None,
            time_max=None,
            max_results=100,
            fetch_all=False,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": None,
            },
        )
        mock_log.set.assert_any_call(calendar={"operation": "get_events", "event_count": 0})

    async def test_get_events_with_date_range(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=[],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.get(
                f"{API}/calendar/events",
                params={"start_date": "2026-03-01", "end_date": "2026-03-31"},
            )
        assert resp.status_code == 200
        mock_svc.get_calendar_events.assert_awaited_once_with(
            user_id=USER_ID,
            selected_calendars=None,
            time_min=START_ISO,
            time_max=END_EXCLUSIVE_ISO,
            max_results=100,
            fetch_all=False,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": 31,
            },
        )

    async def test_get_events_with_start_date_only(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=[],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.get(
                f"{API}/calendar/events",
                params={"start_date": "2026-03-01"},
            )
        assert resp.status_code == 200
        mock_svc.get_calendar_events.assert_awaited_once_with(
            user_id=USER_ID,
            selected_calendars=None,
            time_min=START_ISO,
            time_max=None,
            max_results=100,
            fetch_all=False,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": None,
            },
        )

    async def test_get_events_with_selected_calendars(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=[],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.get(
                f"{API}/calendar/events",
                params={
                    "selected_calendars": ["primary", "work"],
                    "max_results": 25,
                    "fetch_all": True,
                },
            )
        assert resp.status_code == 200
        mock_svc.get_calendar_events.assert_awaited_once_with(
            user_id=USER_ID,
            selected_calendars=["primary", "work"],
            time_min=None,
            time_max=None,
            max_results=25,
            fetch_all=True,
        )

    async def test_get_events_invalid_start_date_returns_400(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True):
            resp = await client.get(
                f"{API}/calendar/events",
                params={"start_date": INVALID_DATE},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == START_DATE_ERROR

    async def test_get_events_invalid_end_date_returns_400(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True):
            resp = await client.get(
                f"{API}/calendar/events",
                params={"end_date": INVALID_DATE},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == END_DATE_ERROR

    async def test_get_events_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.side_effect = Exception("Fail")
            resp = await client.get(f"{API}/calendar/events")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Fail"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/events")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/{calendar_id}/events
# ---------------------------------------------------------------------------


class TestGetEventsByCalendar:
    """GET /api/v1/calendar/{calendar_id}/events"""

    async def test_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events_by_id.return_value = CalendarEventPageResponse(
                events=[GoogleCalendarEventResource(id="ev2")]
            )
            resp = await client.get(f"{API}/calendar/my-cal-id/events")
        assert resp.status_code == 200
        assert resp.json() == {"events": [{"id": "ev2"}], "nextPageToken": None}
        mock_svc.get_calendar_events_by_id.assert_awaited_once_with(
            calendar_id="my-cal-id",
            user_id=USER_ID,
            page_token=None,
            time_min=None,
            time_max=None,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={
                "operation": "get_events",
                "calendar_id": "my-cal-id",
                "time_range_days": None,
            },
        )
        mock_log.set.assert_any_call(calendar={"operation": "get_events", "event_count": 1})

    async def test_with_date_filters_and_page_token(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events_by_id.return_value = CalendarEventPageResponse(
                events=[], next_page_token="tok-2"
            )
            resp = await client.get(
                f"{API}/calendar/primary/events",
                params={
                    "start_date": "2026-01-01",
                    "end_date": "2026-12-31",
                    "page_token": "tok-1",
                },
            )
        assert resp.status_code == 200
        assert resp.json() == {"events": [], "nextPageToken": "tok-2"}
        mock_svc.get_calendar_events_by_id.assert_awaited_once_with(
            calendar_id="primary",
            user_id=USER_ID,
            page_token="tok-1",
            time_min="2026-01-01T00:00:00+00:00",
            time_max="2027-01-01T00:00:00+00:00",
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={
                "operation": "get_events",
                "calendar_id": "primary",
                "time_range_days": 365,
            },
        )

    async def test_invalid_start_date_returns_400(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True):
            resp = await client.get(
                f"{API}/calendar/primary/events",
                params={"start_date": INVALID_DATE},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == START_DATE_ERROR

    async def test_invalid_end_date_returns_400(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True):
            resp = await client.get(
                f"{API}/calendar/primary/events",
                params={"end_date": INVALID_DATE},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == END_DATE_ERROR

    async def test_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events_by_id.side_effect = Exception("Fail")
            resp = await client.get(f"{API}/calendar/primary/events")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Fail"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/primary/events")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/event
# ---------------------------------------------------------------------------


class TestCreateEvent:
    """POST /api/v1/calendar/event"""

    CREATE_PAYLOAD: ClassVar[dict] = {
        "summary": "Lunch",
        "start": "2026-03-20T12:00:00+00:00",
        "end": "2026-03-20T13:00:00+00:00",
    }

    async def test_create_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.return_value = GoogleCalendarEventResource(
                id="ev-new", summary="Lunch"
            )
            resp = await client.post(f"{API}/calendar/event", json=self.CREATE_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json() == {"id": "ev-new", "summary": "Lunch"}
        mock_svc.create_calendar_event.assert_awaited_once_with(
            create_event_model("Lunch", "2026-03-20T12:00:00+00:00", "2026-03-20T13:00:00+00:00"),
            USER_ID,
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={"operation": "create_event", "calendar_id": None},
        )

    async def test_create_event_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.side_effect = Exception("API error")
            resp = await client.post(f"{API}/calendar/event", json=self.CREATE_PAYLOAD)
        assert resp.status_code == 500
        assert resp.json()["detail"] == "API error"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/calendar/event", json=self.CREATE_PAYLOAD)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/v1/calendar/event
# ---------------------------------------------------------------------------


class TestDeleteEvent:
    """DELETE /api/v1/calendar/event"""

    DELETE_PAYLOAD: ClassVar[dict] = {"event_id": "ev-001", "calendar_id": "primary"}

    async def test_delete_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(
                DELETE_PATCH,
                new_callable=AsyncMock,
                return_value=EventDeleteResponse(
                    success=True, message="Event deleted successfully"
                ),
            ) as mock_delete,
        ):
            resp = await client.request("DELETE", f"{API}/calendar/event", json=self.DELETE_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Event deleted successfully"}
        mock_delete.assert_awaited_once_with(delete_event_model("ev-001", "primary"), USER_ID)
        mock_log.set.assert_any_call(user={"id": USER_ID}, calendar={"operation": "delete_event"})

    async def test_delete_event_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(DELETE_PATCH, new_callable=AsyncMock, side_effect=Exception("Not found")),
        ):
            resp = await client.request("DELETE", f"{API}/calendar/event", json=self.DELETE_PAYLOAD)
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Not found"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.request(
            "DELETE", f"{API}/calendar/event", json=self.DELETE_PAYLOAD
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/calendar/event
# ---------------------------------------------------------------------------


class TestUpdateEvent:
    """PUT /api/v1/calendar/event"""

    UPDATE_PAYLOAD: ClassVar[dict] = {"event_id": "ev-001", "summary": "Updated"}

    async def test_update_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(
                UPDATE_PATCH,
                new_callable=AsyncMock,
                return_value=GoogleCalendarEventResource(id="ev-001", summary="Updated"),
            ) as mock_update,
        ):
            resp = await client.put(f"{API}/calendar/event", json=self.UPDATE_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json() == {"id": "ev-001", "summary": "Updated"}
        mock_update.assert_awaited_once_with(update_event_model("ev-001", "Updated"), USER_ID)
        mock_log.set.assert_any_call(user={"id": USER_ID}, calendar={"operation": "update_event"})

    async def test_update_event_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(UPDATE_PATCH, new_callable=AsyncMock, side_effect=Exception("Update failed")),
        ):
            resp = await client.put(f"{API}/calendar/event", json=self.UPDATE_PAYLOAD)
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Update failed"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(f"{API}/calendar/event", json=self.UPDATE_PAYLOAD)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/preferences
# ---------------------------------------------------------------------------


class TestGetCalendarPreferences:
    """GET /api/v1/calendar/preferences"""

    async def test_get_preferences_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_user_calendar_preferences.return_value = CalendarPreferencesResponse(
                selected_calendars=["primary"]
            )
            resp = await client.get(f"{API}/calendar/preferences")
        assert resp.status_code == 200
        # Serialized under the camelCase alias the web client reads.
        assert resp.json() == {"selectedCalendars": ["primary"]}
        mock_svc.get_user_calendar_preferences.assert_awaited_once_with(USER_ID)
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, calendar={"operation": "get_preferences"}
        )

    async def test_get_preferences_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_user_calendar_preferences.side_effect = Exception("DB error")
            resp = await client.get(f"{API}/calendar/preferences")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "DB error"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/preferences")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/calendar/preferences
# ---------------------------------------------------------------------------


class TestUpdateCalendarPreferences:
    """PUT /api/v1/calendar/preferences"""

    async def test_update_preferences_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.update_user_calendar_preferences.return_value = (
                CalendarPreferencesUpdateResponse(message="Preferences updated")
            )
            resp = await client.put(
                f"{API}/calendar/preferences",
                json={"selected_calendars": ["primary", "work"]},
            )
        assert resp.status_code == 200
        assert resp.json() == {"message": "Preferences updated"}
        call_args = mock_svc.update_user_calendar_preferences.await_args
        assert call_args is not None
        assert call_args.args == (USER_ID, ["primary", "work"])
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, calendar={"operation": "update_preferences"}
        )

    async def test_update_preferences_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.update_user_calendar_preferences.side_effect = Exception("DB error")
            resp = await client.put(
                f"{API}/calendar/preferences",
                json={"selected_calendars": ["primary"]},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "DB error"

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(
            f"{API}/calendar/preferences",
            json={"selected_calendars": ["primary"]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/events/batch (create)
# ---------------------------------------------------------------------------


class TestBatchCreateEvents:
    """POST /api/v1/calendar/events/batch"""

    EVENT_1: ClassVar[dict] = {
        "summary": "Event 1",
        "start": "2026-03-20T10:00:00+00:00",
        "end": "2026-03-20T11:00:00+00:00",
    }
    EVENT_2: ClassVar[dict] = {
        "summary": "Event 2",
        "start": "2026-03-20T12:00:00+00:00",
        "end": "2026-03-20T13:00:00+00:00",
    }

    async def test_batch_create_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.return_value = GoogleCalendarEventResource(
                id="ev-batch-1"
            )
            resp = await client.post(
                f"{API}/calendar/events/batch", json={"events": [self.EVENT_1]}
            )
        assert resp.status_code == 200
        assert resp.json() == {"successful": [{"id": "ev-batch-1"}], "failed": []}
        mock_svc.create_calendar_event.assert_awaited_once_with(
            create_event_model("Event 1", "2026-03-20T10:00:00+00:00", "2026-03-20T11:00:00+00:00"),
            USER_ID,
        )
        mock_log.set.assert_any_call(user={"id": USER_ID}, calendar={"operation": "batch_create"})
        mock_log.warning.assert_not_called()

    async def test_batch_create_partial_failure(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.side_effect = [
                Exception("Failed"),
                GoogleCalendarEventResource(id="ev-ok"),
            ]
            resp = await client.post(
                f"{API}/calendar/events/batch",
                json={"events": [self.EVENT_1, self.EVENT_2]},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "successful": [{"id": "ev-ok"}],
            "failed": [{"event": "Event 1", "error": "Failed"}],
        }
        assert mock_svc.create_calendar_event.await_args_list == [
            call(
                create_event_model(
                    "Event 1", "2026-03-20T10:00:00+00:00", "2026-03-20T11:00:00+00:00"
                ),
                USER_ID,
            ),
            call(
                create_event_model(
                    "Event 2", "2026-03-20T12:00:00+00:00", "2026-03-20T13:00:00+00:00"
                ),
                USER_ID,
            ),
        ]
        mock_log.warning.assert_called_once_with(
            "calendar batch item failed", operation="batch_create", error_type="Exception"
        )

    async def test_batch_create_per_event_failure_does_not_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.side_effect = Exception("boom")
            resp = await client.post(
                f"{API}/calendar/events/batch", json={"events": [self.EVENT_1]}
            )
        assert resp.status_code == 200
        assert resp.json() == {"successful": [], "failed": [{"event": "Event 1", "error": "boom"}]}

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/calendar/events/batch",
            json={"events": [self.EVENT_1]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/calendar/events/batch (update)
# ---------------------------------------------------------------------------


class TestBatchUpdateEvents:
    """PUT /api/v1/calendar/events/batch"""

    UPD_1: ClassVar[dict] = {"event_id": "ev-001", "summary": "Updated"}
    UPD_2: ClassVar[dict] = {"event_id": "ev-002", "summary": "Nope"}

    async def test_batch_update_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(
                UPDATE_PATCH,
                new_callable=AsyncMock,
                return_value=GoogleCalendarEventResource(id="ev-001", summary="Updated"),
            ) as mock_update,
        ):
            resp = await client.put(
                f"{API}/calendar/events/batch",
                json={"events": [self.UPD_1]},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "successful": [{"id": "ev-001", "summary": "Updated"}],
            "failed": [],
        }
        mock_update.assert_awaited_once_with(update_event_model("ev-001", "Updated"), USER_ID)
        mock_log.set.assert_any_call(user={"id": USER_ID}, calendar={"operation": "batch_update"})

    async def test_batch_update_partial_failure(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(
                UPDATE_PATCH,
                new_callable=AsyncMock,
                side_effect=[
                    Exception("Not found"),
                    GoogleCalendarEventResource(id="ev-002", summary="Updated"),
                ],
            ) as mock_update,
        ):
            resp = await client.put(
                f"{API}/calendar/events/batch",
                json={"events": [self.UPD_1, self.UPD_2]},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "successful": [{"id": "ev-002", "summary": "Updated"}],
            "failed": [{"event_id": "ev-001", "error": "Not found"}],
        }
        assert mock_update.await_args_list == [
            call(update_event_model("ev-001", "Updated"), USER_ID),
            call(update_event_model("ev-002", "Nope"), USER_ID),
        ]
        mock_log.warning.assert_called_once_with(
            "calendar batch item failed",
            operation="batch_update",
            event_id="ev-001",
            error_type="Exception",
        )

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(
            f"{API}/calendar/events/batch",
            json={"events": [self.UPD_1]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/v1/calendar/events/batch (delete)
# ---------------------------------------------------------------------------


class TestBatchDeleteEvents:
    """DELETE /api/v1/calendar/events/batch"""

    DEL_1: ClassVar[dict] = {"event_id": "ev-001", "calendar_id": "primary"}
    DEL_2: ClassVar[dict] = {"event_id": "ev-002", "calendar_id": "primary"}

    async def test_batch_delete_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(DELETE_PATCH, new_callable=AsyncMock, return_value=None) as mock_delete,
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/calendar/events/batch",
                json={"events": [self.DEL_1]},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "successful": [{"event_id": "ev-001", "calendar_id": "primary"}],
            "failed": [],
        }
        mock_delete.assert_awaited_once_with(delete_event_model("ev-001"), USER_ID)
        mock_log.set.assert_any_call(user={"id": USER_ID}, calendar={"operation": "batch_delete"})

    async def test_batch_delete_partial_failure(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(LOG_PATCH) as mock_log,
            patch(
                DELETE_PATCH,
                new_callable=AsyncMock,
                side_effect=[Exception("Not found"), None],
            ) as mock_delete,
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/calendar/events/batch",
                json={"events": [self.DEL_1, self.DEL_2]},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "successful": [{"event_id": "ev-002", "calendar_id": "primary"}],
            "failed": [{"event_id": "ev-001", "error": "Not found"}],
        }
        assert mock_delete.await_args_list == [
            call(delete_event_model("ev-001"), USER_ID),
            call(delete_event_model("ev-002"), USER_ID),
        ]
        mock_log.warning.assert_called_once_with(
            "calendar batch item failed",
            operation="batch_delete",
            event_id="ev-001",
            error_type="Exception",
        )

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.request(
            "DELETE",
            f"{API}/calendar/events/batch",
            json={"events": [self.DEL_1]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration not connected (403)
# ---------------------------------------------------------------------------


class TestIntegrationNotConnected:
    """Verify endpoints return 403 when calendar integration is not connected."""

    async def test_list_calendars_returns_403(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=False):
            resp = await client.get(f"{API}/calendar/list")
        assert resp.status_code == 403

    async def test_get_events_returns_403(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=False):
            resp = await client.get(f"{API}/calendar/events")
        assert resp.status_code == 403

    async def test_create_event_returns_403(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=False):
            resp = await client.post(
                f"{API}/calendar/event",
                json={
                    "summary": "Test",
                    "start": "2026-03-20T12:00:00+00:00",
                    "end": "2026-03-20T13:00:00+00:00",
                },
            )
        assert resp.status_code == 403
